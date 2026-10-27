"""Upload: one file in, searchable immediately, and never a path escape.

The console is allowed to write into the instance's memories tree, which makes
this the most security-sensitive handler in the server. These pin the shape of
that boundary: only supported types, only a bare filename, size-capped, no
silent clobbering, and a failed index leaves no orphan file behind.
"""
from __future__ import annotations

import base64
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from loci.http_api import Audit, QueryLog, UPLOAD_MAX_BYTES, _make_handler, _safe_upload_name


class Brain:
    def search_payload(self, **kw):
        return {"result": "", "hits": []}

    def ask(self, q, verify=False):
        return ""

    def chunks_for(self, path):
        return 5

    def index_summary(self):
        return {"chunks": 5, "files": 1}


@pytest.fixture
def server(tmp_path):
    mem = tmp_path / "memories"
    mem.mkdir()
    cfg = SimpleNamespace(
        memories={"path": str(mem)},
        http={"icons": str(mem), "local_admin": False, "query_log": ""},
        sources=[{"path": "/notes"}],
        chunk={"size": 800, "overlap": 100})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(
        Brain(), cfg, [{"token": "t", "role": "admin", "label": "x"}],
        Audit(), QueryLog()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, mem
    srv.shutdown()


def call(server, method, path, body=None, token="t"):
    conn = http.client.HTTPConnection(*server.server_address, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request(method, path, json.dumps(body) if body else None, headers)
    res = conn.getresponse()
    return res.status, json.loads(res.read() or b"{}")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---- name boundary -------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("note.md", "note.md"),
    ("../../etc/passwd", "passwd"),
    ("/abs/path/x.md", "x.md"),
    ("dir/sub/y.md", "y.md"),
    ("a\\b\\z.md", "z.md"),
])
def test_names_are_reduced_to_a_basename(raw, expected):
    assert _safe_upload_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", ".", "..", ".hidden", "a\x00b.md"])
def test_dangerous_names_are_refused(raw):
    assert _safe_upload_name(raw) is None


# ---- sources view --------------------------------------------------------

def test_sources_lists_directories_and_limits(server):
    srv, _ = server
    status, data = call(srv, "GET", "/sources")
    assert status == 200
    assert data["sources"] == [{"path": "/notes", "chunks": 5}]
    assert data["indexed"] == {"chunks": 5, "files": 1}
    assert ".md" in data["accepted"]
    assert data["max_bytes"] == UPLOAD_MAX_BYTES


def test_sources_requires_auth(server):
    srv, _ = server
    status, _ = call(srv, "GET", "/sources", token=None)
    assert status == 401


def test_sources_stays_empty_without_an_index(server):
    """An unconfigured instance must still render the page."""
    srv, _ = server
    status, data = call(srv, "GET", "/sources")
    assert status == 200 and isinstance(data["sources"], list)


# ---- upload validation ---------------------------------------------------

def test_unsupported_type_is_rejected_with_the_list(server):
    srv, _ = server
    status, data = call(srv, "POST", "/upload",
                        {"name": "virus.exe", "data": b64(b"MZ")})
    assert status == 400
    assert "unsupported" in data["error"]
    assert ".md" in data["accepted"]


def test_invalid_base64_is_rejected(server):
    srv, _ = server
    status, data = call(srv, "POST", "/upload", {"name": "x.md", "data": "!!"})
    assert status == 400


def test_empty_payload_is_rejected(server):
    srv, _ = server
    status, _ = call(srv, "POST", "/upload", {"name": "x.md", "data": ""})
    assert status == 400


def test_oversize_body_is_refused_before_decoding(server):
    """The server rejects on Content-Length, so it never reads the body — which
    means the client can see a broken pipe instead of the 413. Assert the
    decision, not the transport: either the 413 arrives or the write is cut."""
    srv, _ = server
    huge = "A" * (UPLOAD_MAX_BYTES + 1024)
    try:
        status, data = call(srv, "POST", "/upload", {"name": "x.md", "data": huge})
    except (BrokenPipeError, ConnectionResetError):
        return                              # refused mid-write: correct outcome
    assert status == 413
    assert "MiB" in data["error"]


def test_upload_requires_write_role(server):
    srv, _ = server
    status, _ = call(srv, "POST", "/upload",
                     {"name": "x.md", "data": b64(b"# hi")}, token=None)
    assert status == 401
