"""Preview the real console with synthetic data only; no config, model or DB.

Run: python scripts/preview_console.py --port 8877
Open http://127.0.0.1:8877/ui for documentation screenshots.
All mutations and model calls are disabled. Only the three checked-in UI
assets are served from disk; every API response below is a fixed fixture.
"""
import argparse
import sys
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

WEB = Path(__file__).resolve().parents[1] / "src/loci/web"

def _version() -> str:
    """Version only — no config, database or model import."""
    try:
        from loci import __version__
        return __version__
    except ImportError:                    # running straight from the checkout
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        try:
            from loci import __version__
            return __version__
        except Exception:
            return "0.0.0-preview"


VERSION = _version()
HARNESSES = [
    {"name": name, "display": display, "icon": icon,
     "files": files, "chunks": chunks, "last_updated": "2026-10-19 09:30",
     "summary": {"status": "fresh"}}
    for name, display, icon, files, chunks in [
        ("codex", "Codex", "C", 8, 32),
        ("claude", "Claude Code", "A", 6, 24),
        ("dsh", "DeepSeek Harness", "D", 5, 18),
        ("zcode", "ZCode", "Z", 7, 26),
    ]
]
# read-side log fixture: same shape the server returns, fictional queries only
QUERIES = [
    {"ts": "2026-10-26 09:41:07", "label": "Demo data", "role": "viewer",
     "kind": "search", "query": "why did the humidity sensor replace the BME280",
     "hits": 4, "top": "atlas/decisions.md > ADR-001: SHT45 over BME280", "ms": 4.2},
    {"ts": "2026-10-26 09:40:51", "label": "Demo data", "role": "viewer",
     "kind": "ask", "query": "what broke in the first fortnight",
     "hits": 0, "top": "", "ms": 1.9},
    {"ts": "2026-10-26 09:38:12", "label": "Demo data", "role": "viewer",
     "kind": "search", "query": "release checklist before tagging",
     "hits": 2, "top": "atlas/release-checklist.md > Before tagging", "ms": 3.1},
]

NOTE = """# Project Atlas — demo memory

This is fictional documentation data, not a connected knowledge base.

## Release checklist

- Run the offline test suite before publishing.
- Include source references in project decisions.
- Keep credentials outside the repository.

## Shared context

The team uses Markdown notes so decisions remain readable across tools.
"""


class Preview(BaseHTTPRequestHandler):
    def send(self, status, data, mime="application/json; charset=utf-8"):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path).path
        assets = {"/ui": ("index.html", "text/html; charset=utf-8"),
                  "/ui/app.js": ("app.js", "application/javascript"),
                  "/ui/style.css": ("style.css", "text/css")}
        if route in assets:
            name, mime = assets[route]
            return self.send(200, (WEB / name).read_bytes(), mime)
        if route == "/health":
            return self.send(200, {"status": "ok", "version": VERSION,
                                   "me": {"label": "Demo data", "role": "viewer"}})
        if route == "/harness":
            return self.send(200, {"harness": HARNESSES})
        if route == "/harness-files":
            name = parse_qs(urlsplit(self.path).query).get("name", ["codex"])[0]
            return self.send(200, {"name": name, "display": next((h["display"] for h in HARNESSES if h["name"] == name), name), "files": [
                {"path": "/demo/atlas/decisions.md", "rel": "atlas/decisions.md", "size": len(NOTE), "mtime": "2026-10-19 09:30"},
                {"path": "/demo/atlas/release-checklist.md", "rel": "atlas/release-checklist.md", "size": 180, "mtime": "2026-10-19 09:30"},
                {"path": "/demo/preferences.md", "rel": "preferences.md", "size": 120, "mtime": "2026-10-19 09:30"}]})
        if route == "/source-file":
            return self.send(200, {"path": "/demo/atlas/decisions.md", "text": NOTE})
        if route == "/memories":
            return self.send(200, {"memories": [
                {"name": "release-checklist.md", "title": "Release checklist", "group": "shared", "harness": "", "size": len(NOTE), "mtime": "2026-10-19 09:30"}]})
        if route == "/memory":
            return self.send(200, {"name": "release-checklist.md", "text": NOTE})
        if route == "/stats":
            return self.send(200, {"stats": "Demo fixture · 100 chunks · no database connected", "harness": HARNESSES})
        if route == "/audit":
            return self.send(200, {"audit": []})
        if route == "/queries":
            return self.send(200, {"queries": QUERIES})
        self.send(404, {"error": "not found"})

    # fixed search fixture: no retriever, no embeddings, no model call — just
    # the shape the console renders, so the evidence pane can be reviewed
    SEARCH_HITS = [
        {"source": "atlas/decisions.md", "section": "ADR-001: SHT45 over BME280",
         "text": "## ADR-001: SHT45 over BME280\n\n**Context.** Revision A used a "
                 "BME280 because it was already in the parts bin and does "
                 "temperature, humidity and pressure in one package.\n\n"
                 "**Decision.** A sensor whose error grows exactly where it is "
                 "installed is not worth the EUR 2.50 saved.",
         "tags": "atlas,hardware,adr", "distance": 0.0},
        {"source": "atlas/decisions.md", "section": "ADR-002: ESP32-C6",
         "text": "## ADR-002: ESP32-C6 over nRF52840\n\nThe nRF52840 wins on "
                 "sleep current, but the difference is 10 uA against a 1.2 mA "
                 "average — it changes the battery estimate by less than a day.",
         "tags": "atlas,hardware,adr", "distance": 0.37},
        {"source": "atlas/release-checklist.md", "section": "Before tagging",
         "text": "Before tagging: bump the version in pyproject.toml, add the "
                 "CHANGELOG entry, run the offline suite, then rebuild the "
                 "wheel and check the bundle contents.",
         "tags": "atlas,release", "distance": 0.55},
    ]

    def do_POST(self):
        route = urlsplit(self.path).path
        body = self._body()
        if route == "/search":
            q = str(body.get("query", "") or "")
            hits = self.SEARCH_HITS if q else []
            text = "\n\n".join(
                f"[{i}] {h['source']} > {h['section']}\n{h['text'][:500]}"
                for i, h in enumerate(hits, 1)) or "(no results)"
            return self.send(200, {"result": text, "hits": hits})
        return self.send(403, {"error": "Read-only demo: writes and model calls are disabled."})

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    do_DELETE = do_POST

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Preview)
    print(f"Synthetic-data preview: http://127.0.0.1:{args.port}/ui", flush=True)
    server.serve_forever()
