"""HTTP REST API over the same pipeline (search/ask/remember/stats/links).

Usage: loci serve-http [--host H] [--port P]
Auth: Bearer token from [http] token in config (auto-generated if empty)."""
from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from loci.mcp_server import Brain


def run_server(cfg, host: str, port: int) -> None:
    token = cfg.http.get("token") or secrets.token_hex(16)
    brain = Brain()
    brain._ensure()
    handler = _make_handler(brain, token)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"HTTP API: http://{host}:{port}")
    print(f"auth: Authorization: Bearer {token[:8]}...  (full token in config)")
    server.serve_forever()


def _make_handler(brain, token):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def _guard(self, fn):
            """Run a handler; any exception becomes a 500 JSON response instead
            of killing the connection (e.g. empty queries hitting the embedder)."""
            try:
                return fn()
            except Exception as e:
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            if self.path == "/health":
                return self._json(200, {"status": "ok"})
            if self.path == "/stats":
                return self._guard(lambda: self._json(
                    200, {"stats": brain.stats()}))
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid JSON body"})
            if self.path == "/search":
                return self._guard(lambda: self._json(200, {"result": brain.search(**{
                    "query": body.get("query", ""), "k": body.get("k"),
                    "tag": body.get("tag"), "path_contains": body.get("in")})}))
            if self.path == "/ask":
                return self._guard(lambda: self._json(200, {"result": brain.ask(
                    body.get("question", ""), verify=body.get("verify", False))}))
            if self.path == "/remember":
                return self._guard(lambda: self._json(200, {"result": brain.remember(
                    body.get("text", ""), title=body.get("title"),
                    tags=body.get("tags"))}))
            self._json(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            pass

    return Handler
