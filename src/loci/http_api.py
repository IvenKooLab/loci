"""HTTP REST API + built-in web console over the same pipeline.

Endpoints (Bearer auth; see [[auth.tokens]] in config.toml):
  GET  /health                        any role
  GET  /stats                         index stats + per-harness rows
  POST /search /ask                   read-only queries
  GET  /memories                      list shared + harness memory notes
  GET  /memory?name=                  one note's raw markdown
  POST /memory                        create (title/text/tags) or update (name/text)
  DELETE /memory?name=                soft-delete into .trash
  GET  /source-file?path=             raw harness memory file (path-jailed)
  GET  /harness                       per-harness stats
  POST /harness                       {"action":"summarize","name"?,"force"?}
  POST /ingest                        incremental re-index
  GET  /audit                         recent write/audit events
  GET  /ui /ui/app.js /ui/style.css   web console (static shell, data is authed)
  GET  /icons/<file>                  harness icons from the instance icons dir

Roles: viewer (read) < editor (+memory writes) < admin (+ingest/summarize/audit).
The legacy single [http] token keeps working and maps to admin.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

from loci.mcp_server import Brain

WEB_DIR = Path(__file__).resolve().parent / "web"
ROLES = {"viewer": 0, "editor": 1, "admin": 2}


def _auth_table(cfg) -> list[dict]:
    """Merge [[auth.tokens]] entries with the legacy single [http] token."""
    entries = []
    for t in getattr(cfg, "auth", None) or []:
        token = str(t.get("token", "")).strip()
        if not token:
            continue
        role = str(t.get("role", "viewer")).strip().lower()
        entries.append({"token": token,
                        "role": role if role in ROLES else "viewer",
                        "label": str(t.get("label", "")) or "unnamed"})
    legacy = cfg.http.get("token")
    if legacy:
        entries.append({"token": legacy, "role": "admin", "label": "legacy"})
    if not entries:                          # unconfigured: random admin token
        entries.append({"token": secrets.token_hex(16), "role": "admin",
                        "label": "auto-generated"})
    return entries


def resolve_auth(entries: list[dict], authorization: str) -> dict | None:
    """Bearer token → auth entry (with role/label); None when unrecognized."""
    if not authorization.startswith("Bearer "):
        return None
    given = authorization[7:].strip()
    for e in entries:
        if secrets.compare_digest(e["token"], given):
            return e
    return None


def effective_entry(resolved: dict | None, authorization: str, client_ip: str,
                    local_admin: bool = True) -> dict | None:
    """Loopback connections without any credentials are trusted as admin — the
    console binds to 127.0.0.1 anyway, so typing a token on your own machine is
    pure friction. A presented-but-invalid token is still rejected (a viewer's
    typo must never escalate to admin). Disable the trust with
    `[http] local_admin = false` when serving through a reverse proxy or SSH
    tunnel (tunneled traffic also arrives on loopback!)."""
    if resolved is not None:
        return resolved
    if local_admin and not authorization.strip() \
            and client_ip in ("127.0.0.1", "::1"):
        return {"token": "", "role": "admin", "label": "local"}
    return None


def allowed(entry: dict | None, level: str) -> bool:
    """level: read | write | admin."""
    if entry is None:
        return False
    return ROLES.get(entry["role"], 0) >= ROLES.get(
        {"read": "viewer", "write": "editor", "admin": "admin"}[level], 99)


class Audit:
    """Ring buffer of write/admin events — shown in the console, kept for
    GET /audit (in-memory only: restarts start fresh; stderr has the history)."""

    def __init__(self, maxlen: int = 500):
        self._buf = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, entry: dict, action: str, detail: str = "") -> None:
        item = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "label": entry["label"], "role": entry["role"],
                "action": action, "detail": detail[:200]}
        with self._lock:
            self._buf.appendleft(item)
        print(f"audit: {item['ts']} {item['label']}({item['role']}) "
              f"{action} {detail[:120]}", file=sys.stderr)

    def recent(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return list(self._buf)[:limit]


def run_server(cfg, host: str, port: int) -> None:
    brain = Brain()
    brain._ensure()
    entries = _auth_table(cfg)
    if not getattr(cfg, "auth", None):       # only the legacy/auto token exists
        print(f"auth: Authorization: Bearer {entries[0]['token'][:8]}...  "
              "(single-token mode, role admin — add [[auth.tokens]] for roles)")
    else:
        print(f"auth: {len(entries)} token(s): "
              + ", ".join(f"{e['label']}={e['role']}" for e in entries))
    handler = _make_handler(brain, cfg, entries, Audit())
    server = ThreadingHTTPServer((host, port), handler)
    print(f"HTTP API: http://{host}:{port}  (console at /ui)")
    server.serve_forever()


def _make_handler(brain, cfg, entries, audit):
    mem_dir = Path(cfg.memories["path"]).expanduser().resolve()
    icons_dir = Path(cfg.http.get("icons", "./icons")).expanduser().resolve()
    from loci import harness as harness_mod
    local_admin = bool(cfg.http.get("local_admin", True))

    def _harnesses():
        return harness_mod.load_harnesses(cfg)

    class Handler(BaseHTTPRequestHandler):
        entry: dict | None = None

        def _json(self, code: int, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, code: int, data: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _file(self, rel: str, ctype: str) -> bool:
            p = WEB_DIR / rel
            if p.resolve().parent != WEB_DIR.resolve() or not p.exists():
                return False
            self._bytes(200, p.read_bytes(), ctype)
            return True

        def _query(self) -> dict:
            return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

        def _guard(self, fn):
            """Run a handler; any exception becomes a 500 JSON response instead
            of killing the connection."""
            try:
                return fn()
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})

        # ---- path-jailed file access ----

        def _safe_memory(self, name: str) -> Path | None:
            p = (mem_dir / name).resolve()
            return p if p.is_file() and p.suffix == ".md" \
                and str(p).startswith(str(mem_dir)) else None

        def _safe_source(self, path: str) -> Path | None:
            roots = [r for h in _harnesses() for r in h.roots] + [mem_dir]
            try:
                p = Path(unquote(path)).expanduser().resolve()
            except (OSError, RuntimeError):
                return None
            if p.suffix not in (".md", ".txt") or not p.is_file():
                return None
            return p if any(str(p).startswith(str(r)) for r in roots) else None

        def _reindex_file(self, path: Path) -> None:
            try:
                from loci.memories import index_memory_file
                index_memory_file(cfg, str(path))
            except Exception:
                pass                                # replayable via /ingest

        # ---- verbs ----

        def do_GET(self):
            self.entry = effective_entry(
                resolve_auth(entries, self.headers.get("Authorization", "")),
                self.headers.get("Authorization", ""),
                self.client_address[0], local_admin)
            route, q = urlsplit(self.path).path, self._query()
            if route == "/ui":                      # public shell; data is authed
                if self._file("index.html", "text/html; charset=utf-8"):
                    return
            if route == "/ui/app.js":
                if self._file("app.js", "application/javascript; charset=utf-8"):
                    return
            if route == "/ui/style.css":
                if self._file("style.css", "text/css; charset=utf-8"):
                    return
            if route.startswith("/icons/"):         # logos: public, non-sensitive
                name = Path(route[len("/icons/"):]).name
                p = icons_dir / name
                if p.is_file() and str(p.resolve()).startswith(str(icons_dir)):
                    ctypes = {".png": "image/png", ".svg": "image/svg+xml",
                              ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                              ".gif": "image/gif", ".webp": "image/webp"}
                    self._bytes(200, p.read_bytes(),
                                ctypes.get(p.suffix, "application/octet-stream"))
                    return
                return self._json(404, {"error": "not found"})
            if not allowed(self.entry, "read"):
                return self._json(401, {"error": "unauthorized"})
            if route == "/health":
                return self._json(200, {"status": "ok",
                                        "me": {"label": self.entry["label"],
                                               "role": self.entry["role"]}})
            if route == "/stats":
                return self._guard(lambda: self._json(200, {
                    "stats": brain.stats(),
                    "harness": harness_mod.stats(cfg, brain._store, _harnesses())
                    if _harnesses() else []}))
            if route == "/harness":
                return self._guard(lambda: self._json(
                    200, {"harness": harness_mod.stats(cfg, brain._store, _harnesses())}))
            if route == "/harness-files":
                name = q.get("name", "")
                matches = [h for h in _harnesses() if h.name == name]
                if not matches:
                    return self._json(404, {"error": f"no harness named '{name}'"})
                h = matches[0]
                files = []
                for p in harness_mod.memory_files(h):
                    rel = next((str(p.relative_to(r)) for r in h.roots
                                if str(p).startswith(str(r))), p.name)
                    st = p.stat()
                    files.append({
                        "path": str(p), "rel": rel,
                        "size": st.st_size,
                        "mtime": datetime.fromtimestamp(
                            st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                return self._json(200, {"name": h.name,
                                        "display": h.display or h.name,
                                        "files": files})
            if route == "/memories":
                return self._guard(lambda: self._json(200, {
                    "memories": self._list_memories()}))
            if route == "/memory":
                p = self._safe_memory(q.get("name", ""))
                if not p:
                    return self._json(404, {"error": "not found"})
                return self._guard(lambda: self._json(
                    200, {"name": q["name"], "text": p.read_text(encoding="utf-8",
                                                                 errors="replace")}))
            if route == "/source-file":
                p = self._safe_source(q.get("path", ""))
                if not p:
                    return self._json(404, {"error": "not found"})
                return self._guard(lambda: self._json(200, {
                    "path": str(p), "text": p.read_text(encoding="utf-8",
                                                        errors="replace")}))
            if route == "/audit":
                if not allowed(self.entry, "admin"):
                    return self._json(403, {"error": "forbidden"})
                return self._json(200, {"audit": audit.recent()})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            self.entry = effective_entry(
                resolve_auth(entries, self.headers.get("Authorization", "")),
                self.headers.get("Authorization", ""),
                self.client_address[0], local_admin)
            route = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid JSON body"})
            if route in ("/search", "/ask"):
                if not allowed(self.entry, "read"):
                    return self._json(401, {"error": "unauthorized"})
                if route == "/search":
                    return self._guard(lambda: self._json(200, {"result": brain.search(**{
                        "query": body.get("query", ""), "k": body.get("k"),
                        "tag": body.get("tag"),
                        "path_contains": body.get("in")})}))
                return self._guard(lambda: self._json(200, {"result": brain.ask(
                    body.get("question", ""), verify=body.get("verify", False))}))
            if not allowed(self.entry, "write"):
                return self._json(allowed(self.entry, "read")
                                  and 403 or 401, {"error": "forbidden"})
            if route == "/remember":
                out = brain.remember(body.get("text", ""), title=body.get("title"),
                                     tags=body.get("tags"))
                audit.add(self.entry, "remember", str(body.get("title", "")))
                return self._guard(lambda: self._json(200, {"result": out}))
            if route == "/memory":
                return self._guard(lambda: self._memory_write(body))
            if not allowed(self.entry, "admin"):
                return self._json(403, {"error": "forbidden"})
            if route == "/ingest":
                out = brain.ingest(force=bool(body.get("force")))
                audit.add(self.entry, "ingest", f"force={bool(body.get('force'))}")
                return self._guard(lambda: self._json(200, {"result": out}))
            if route == "/harness":
                out = brain.harness_summarize(name=body.get("name"),
                                              force=bool(body.get("force")))
                audit.add(self.entry, "harness.summarize",
                          str(body.get("name") or "all"))
                return self._guard(lambda: self._json(200, {"result": out}))
            self._json(404, {"error": "not found"})

        def do_DELETE(self):
            self.entry = effective_entry(
                resolve_auth(entries, self.headers.get("Authorization", "")),
                self.headers.get("Authorization", ""),
                self.client_address[0], local_admin)
            if not allowed(self.entry, "write"):
                return self._json(401, {"error": "unauthorized"})
            if urlsplit(self.path).path != "/memory":
                return self._json(404, {"error": "not found"})
            return self._guard(lambda: self._memory_delete(self._query().get("name", "")))

        def _memory_write(self, body):
            text = str(body.get("text", "")).strip()
            if not text:
                return self._json(400, {"error": "text is required"})
            name = body.get("name")
            if name:                              # update: keep frontmatter
                p = self._safe_memory(str(name))
                if not p:
                    return self._json(404, {"error": "not found"})
                raw = p.read_text(encoding="utf-8", errors="replace")
                fm = f"---{raw.split('---', 2)[1]}---" if raw.startswith("---") else ""
                tmp = p.with_suffix(".md.tmp")
                tmp.write_text(f"{fm}\n{text}\n" if fm else f"{text}\n",
                               encoding="utf-8")
                tmp.rename(p)
                self._reindex_file(p)
                audit.add(self.entry, "memory.update", str(name))
                return self._json(200, {"path": str(p)})
            from loci.memories import write_memory
            path = write_memory(str(mem_dir), text, title=body.get("title"),
                                tags=body.get("tags"))
            self._reindex_file(Path(path))
            audit.add(self.entry, "memory.create", str(body.get("title", "")))
            return self._json(200, {"path": path})

        def _memory_delete(self, name: str):
            p = self._safe_memory(name)
            if not p:
                return self._json(404, {"error": "not found"})
            trash = mem_dir / ".trash"
            trash.mkdir(parents=True, exist_ok=True)
            dest, n = trash / p.name, 2
            while dest.exists():
                dest = trash / f"{p.stem}-{n}{p.suffix}"
                n += 1
            p.rename(dest)
            brain._store.delete_file(str(p))      # drop its chunks immediately
            audit.add(self.entry, "memory.delete", str(name))
            return self._json(200, {"trashed": str(dest)})

        def _list_memories(self):
            rows = []
            for p in sorted(list(mem_dir.glob("*.md"))
                            + list(mem_dir.glob("harness/*.md"))):
                if p.parent.name == ".trash":
                    continue
                rel = p.relative_to(mem_dir)
                group = "harness" if rel.parts[0] == "harness" else "shared"
                # harness: which tool owns this note (harness/<name>.md);
                # title: frontmatter title:, else the file stem — never the
                # raw '---' fence a title-less frontmatter would yield
                head = p.read_text(encoding="utf-8", errors="ignore")[:400]
                title = ""
                if head.startswith("---"):
                    m = re.search(r"^title:\s*(.+)$", head, re.M)
                    if m:
                        title = m.group(1).strip().strip('"')[:80]
                rows.append({
                    "name": str(rel),
                    "group": group,
                    "harness": rel.parts[1].rsplit(".", 1)[0]
                               if group == "harness" else "",
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(
                        p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "title": title or p.stem,
                })
            return rows

        def log_message(self, fmt, *args):
            pass

    return Handler
