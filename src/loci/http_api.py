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

import base64
import binascii
import errno
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
from urllib.parse import urlsplit, parse_qs

from loci import __version__
from loci.mcp_server import Brain

WEB_DIR = Path(__file__).resolve().parent / "web"
ROLES = {"viewer": 0, "editor": 1, "admin": 2}


def _within(path: Path, root: Path) -> bool:
    """Compare resolved path components, not similarly named directory prefixes."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


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


# a single uploaded document, base64-expanded; 16 MiB is ~12 MiB of file
UPLOAD_MAX_BYTES = 16 << 20


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


class QueryLog:
    """Read-side log: who searched what, and what came back.

    Deliberately separate from `Audit` — that one is a *write* trail and is
    admin-only. This answers the question multiple agents sharing one instance
    actually ask: "why did Codex get nothing when I get results?" A search that
    hit the wrong LOCI_HOME, or ran before an ingest, shows up here as a query
    with zero hits, which no amount of write-auditing reveals.

    Stores the query text and the top hit's location, never the hit content.
    In-memory ring buffer plus an optional JSONL append (`[http] query_log`),
    so a restart keeps the recent past only if the file is enabled."""

    def __init__(self, maxlen: int = 500, path: str | None = None):
        self._buf = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._path = Path(path).expanduser() if path else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, entry: dict, kind: str, query: str, hits: list[dict],
            ms: float, n: int | None = None) -> None:
        top = hits[0] if hits else {}
        item = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label": entry["label"], "role": entry["role"], "kind": kind,
            "query": query[:300],
            "hits": len(hits) if n is None else n,
            "top": (top.get("source", "") +
                    (f" > {top['section']}" if top.get("section") else "")),
            "ms": round(ms, 1),
        }
        with self._lock:
            self._buf.appendleft(item)
            if self._path:
                try:
                    with self._path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(item, ensure_ascii=False) + "\n")
                except OSError:
                    pass                    # logging must never break a search

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
    handler = _make_handler(brain, cfg, entries, Audit(),
                            QueryLog(path=cfg.http.get("query_log")))
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as e:
        # two loci instances (different LOCI_HOME) on one host is a normal
        # thing to do, and the traceback Chrome/uvicorn users see says nothing
        # useful — name the port, the likely cause and the two ways out
        if e.errno not in (errno.EADDRINUSE, errno.EACCES):
            raise
        reason = ("already in use — another loci instance is probably running"
                  if e.errno == errno.EADDRINUSE
                  else "needs privileges the current user does not have")
        raise SystemExit(
            f"loci: cannot listen on {host}:{port} ({reason}).\n"
            f"  find it:      lsof -i :{port}\n"
            f"  another port: loci serve-http --port {port + 1}\n"
            f"  or pick one:  loci serve-http --port 0   "
            f"(prints the port it got)\n"
            f"  make it permanent: [http] port = {port + 1} in config.toml")
    bound = server.server_address[1]
    print(f"loci {__version__} — HTTP API: http://{host}:{bound}  (console at /ui)")
    if bound != port:
        print(f"port {port} was taken, listening on {bound} instead")
    server.serve_forever()


def _safe_upload_name(name: str) -> str | None:
    """A bare filename with no path parts, no traversal, no leading dot.

    Uploads are user input landing on disk: take the basename only, refuse
    anything that could escape the uploads directory, and keep the extension.
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not base or base.startswith(".") or base in (".", ".."):
        return None
    if any(c in base for c in ("\x00", "\n", "\r")):
        return None
    return base[:120]


def _make_handler(brain, cfg, entries, audit, queries: "QueryLog | None" = None):
    mem_dir = Path(cfg.memories["path"]).expanduser().resolve()
    upload_dir = mem_dir / "uploads"
    from loci import loaders as loaders_mod
    from loci import harness as harness_mod
    icons_dir = harness_mod.icons_dir_for(cfg).resolve()
    local_admin = bool(cfg.http.get("local_admin", True))

    def _harnesses():
        return harness_mod.load_harnesses(cfg)

    def _log_query(entry, kind: str, query: str, payload, ms: float) -> None:
        """Record one read. Logging must never be able to break a search, so
        every failure here is swallowed."""
        if queries is None:
            return
        try:
            hits = payload.get("hits") if isinstance(payload, dict) else None
            queries.add(entry, kind, str(query or ""), hits or [], ms,
                        n=None if hits is not None else 0)
        except Exception:
            pass

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
            try:
                p = (mem_dir / name).resolve()
                return p if _within(p, mem_dir) and p.is_file() \
                    and p.suffix == ".md" else None
            except (OSError, RuntimeError, ValueError):
                return None

        def _safe_source(self, path: str) -> Path | None:
            roots = [r for h in _harnesses() for r in h.roots] + [mem_dir]
            try:
                p = Path(path).expanduser().resolve()
                if p.suffix not in (".md", ".txt") or not p.is_file():
                    return None
                return p if any(_within(p, r) for r in roots) else None
            except (OSError, RuntimeError, ValueError):
                return None

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
                if p.is_file() and _within(p, icons_dir):
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
                                        "version": __version__,
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
            if route == "/graph":
                def _graph_payload():
                    store = brain._store
                    per = store.per_source()
                    link_map = store.link_map()
                    nodes: dict = {}
                    links = []
                    for src, targets in link_map.items():
                        nodes[src] = per.get(src, 0)
                        for t in [t for t in targets.split(",") if t]:
                            nodes[t] = nodes.get(t, 0)
                            links.append([src, t])
                    for src, n in per.items():
                        nodes.setdefault(src, n)
                    return {"nodes": [{"path": p, "chunks": n}
                                      for p, n in sorted(nodes.items())],
                            "links": links}
                return self._guard(lambda: self._json(200, _graph_payload()))
            if route == "/harness-files":
                name = q.get("name", "")
                matches = [h for h in _harnesses() if h.name == name]
                if not matches:
                    return self._json(404, {"error": f"no harness named '{name}'"})
                h = matches[0]
                files = []
                for p in harness_mod.memory_files(h):
                    rel = next((str(p.relative_to(r)) for r in h.roots
                                if p.is_relative_to(r)), p.name)
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
            if route == "/sources":
                if not allowed(self.entry, "read"):
                    return self._json(401, {"error": "unauthorized"})
                return self._guard(lambda: self._json(200, {
                    "sources": [{"path": str(s.get("path", "")),
                                 "chunks": brain.chunks_for(s.get("path", ""))}
                                for s in (cfg.sources or [])],
                    "uploads_dir": str(upload_dir),
                    "accepted": loaders_mod.supported_suffixes(),
                    "max_bytes": UPLOAD_MAX_BYTES,
                    "indexed": brain.index_summary()}))
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
            if route == "/queries":
                if not allowed(self.entry, "read"):
                    return self._json(401, {"error": "unauthorized"})
                limit = 100
                try:
                    limit = max(1, min(int(q.get("limit", 100)), 500))
                except (TypeError, ValueError):
                    pass
                return self._json(200, {"queries":
                                        queries.recent(limit) if queries else []})
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
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return self._json(400, {"error": "invalid Content-Length"})
            if length < 0:
                return self._json(400, {"error": "invalid Content-Length"})
            # body size: an upload carries base64 file bytes, everything else
            # is small control JSON — keep the tight cap where it belongs
            limit = UPLOAD_MAX_BYTES if route == "/upload" else 1 << 20
            if length > limit:
                return self._json(413, {
                    "error": f"body exceeds {limit // (1 << 20)} MiB"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._json(400, {"error": "invalid JSON body"})
            if not isinstance(body, dict):
                return self._json(400, {"error": "JSON body must be an object"})
            return self._guard(lambda: self._post(route, body))

        def _post(self, route, body):
            if route in ("/search", "/ask"):
                if not allowed(self.entry, "read"):
                    return self._json(401, {"error": "unauthorized"})
                if route == "/search":
                    # `result` unchanged; `hits` is additive so the console can
                    # render an evidence pane, and text-only clients ignore it
                    started = time.perf_counter()
                    payload = brain.search_payload(**{
                        "query": body.get("query", ""), "k": body.get("k"),
                        "tag": body.get("tag"),
                        "path_contains": body.get("in")})
                    _log_query(self.entry, "search", body.get("query", ""),
                               payload, (time.perf_counter() - started) * 1000)
                    return self._json(200, payload)
                started = time.perf_counter()
                text = brain.ask(body.get("question", ""),
                                 verify=body.get("verify", False))
                _log_query(self.entry, "ask", body.get("question", ""),
                           None, (time.perf_counter() - started) * 1000)
                return self._json(200, {"result": text})
            if not allowed(self.entry, "write"):
                return self._json(allowed(self.entry, "read")
                                  and 403 or 401, {"error": "forbidden"})
            if route == "/upload":
                return self._upload(body)
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

        def _upload(self, body):
            """Store one uploaded document and index it immediately.

            `{name, data}` where data is base64. The file lands in the instance's
            uploads directory (inside the memories tree, so it is picked up by
            `ingest`/`watch` afterwards like any other memory), then goes
            straight into the index so it is searchable without a rebuild.
            """
            name = _safe_upload_name(str(body.get("name", "")))
            if not name:
                return self._json(400, {"error": "name is required"})
            if Path(name).suffix.lower() not in set(loaders_mod.supported_suffixes()):
                return self._json(400, {
                    "error": f"unsupported type {Path(name).suffix or '(none)'}",
                    "accepted": loaders_mod.supported_suffixes()})
            raw = str(body.get("data", ""))
            try:
                blob = base64.b64decode(raw.split(",", 1)[-1], validate=True)
            except (ValueError, binascii.Error):
                return self._json(400, {"error": "data must be base64"})
            if not blob:
                return self._json(400, {"error": "empty file"})
            if len(blob) > UPLOAD_MAX_BYTES:
                return self._json(413, {"error": "file too large"})
            upload_dir.mkdir(parents=True, exist_ok=True)
            dest = upload_dir / name
            if dest.exists():                    # never clobber silently
                stem, suf = dest.stem, dest.suffix
                n = 2
                while dest.exists():
                    dest = upload_dir / f"{stem}-{n}{suf}"
                    n += 1
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(blob)
            tmp.replace(dest)
            try:
                from loci.memories import index_document_file
                chunks = index_document_file(cfg, str(dest))
            except Exception as e:
                dest.unlink(missing_ok=True)
                return self._json(400, {"error": f"{type(e).__name__}: {e}"})
            audit.add(self.entry, "upload", f"{dest.name} ({chunks} chunks)")
            return self._json(200, {"file": dest.name, "path": str(dest),
                                    "chunks": chunks,
                                    "bytes": len(blob)})

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
                if not self._safe_memory(str(p)) or p.parent.name == ".trash":
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
