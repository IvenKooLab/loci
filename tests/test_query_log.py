"""The read-side log: who searched what, and what came back.

Kept separate from the write `Audit` because the failure it explains — "the
agent got nothing" — is invisible to write auditing. What matters for review:
it records the query but never the returned text, and it can never break a
search.
"""
from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from loci.http_api import Audit, QueryLog, _make_handler

HITS = [{"source": "projects/a/decisions.md", "section": "ADR-001",
         "text": "SECRET BODY TEXT", "tags": "", "distance": 0.1}]


class Brain:
    def search_payload(self, query, k=None, tag=None, path_contains=None):
        return {"result": "[1] …", "hits": HITS if query.strip() else []}

    def ask(self, question, verify=False):
        return "an answer"


@pytest.fixture
def server(tmp_path):
    log_path = tmp_path / "queries.jsonl"
    cfg = SimpleNamespace(memories={"path": str(tmp_path)},
                          http={"icons": str(tmp_path), "local_admin": False,
                                "query_log": str(log_path)})
    log = QueryLog(path=str(log_path))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(
        Brain(), cfg, [{"token": "t", "role": "admin", "label": "codex"}],
        Audit(), log))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, log_path
    srv.shutdown()


def call(server, method, path, body=None):
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    conn.request(method, path, json.dumps(body) if body else None,
                 {"Authorization": "Bearer t", "Content-Type": "application/json"})
    res = conn.getresponse()
    return res.status, json.loads(res.read() or b"{}")


def test_search_is_logged_with_its_top_hit(server):
    srv, _ = server
    call(srv, "POST", "/search", {"query": "why sht45"})
    _, data = call(srv, "GET", "/queries")
    row = data["queries"][0]
    assert row["kind"] == "search"
    assert row["query"] == "why sht45"
    assert row["hits"] == 1
    assert row["top"] == "projects/a/decisions.md > ADR-001"
    assert row["label"] == "codex"


def test_ask_is_logged_without_hit_detail(server):
    srv, _ = server
    call(srv, "POST", "/ask", {"question": "what broke"})
    _, data = call(srv, "GET", "/queries")
    row = data["queries"][0]
    assert row["kind"] == "ask"
    assert row["hits"] == 0            # ask does not expose its hits
    assert row["top"] == ""


def test_a_miss_is_visible(server):
    """The whole point: a query that returned nothing must look different."""
    srv, _ = server
    call(srv, "POST", "/search", {"query": "   "})
    _, data = call(srv, "GET", "/queries")
    assert data["queries"][0]["hits"] == 0


def test_body_text_is_never_stored(server):
    srv, log_path = server
    call(srv, "POST", "/search", {"query": "q"})
    _, data = call(srv, "GET", "/queries")
    assert "SECRET BODY TEXT" not in json.dumps(data)
    if log_path.exists():
        assert "SECRET BODY TEXT" not in log_path.read_text(encoding="utf-8")


def test_jsonl_append_is_optional_and_line_delimited(server):
    srv, log_path = server
    call(srv, "POST", "/search", {"query": "one"})
    call(srv, "POST", "/ask", {"question": "two"})
    lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln]
    assert len(lines) == 2
    for line in lines:
        assert set(json.loads(line)) >= {"ts", "label", "kind", "query", "hits"}


def test_logging_failure_cannot_break_a_search(tmp_path):
    """A read-only log path must not turn a good search into a 500."""
    cfg = SimpleNamespace(memories={"path": str(tmp_path)},
                          http={"icons": str(tmp_path), "local_admin": False,
                                "query_log": "/proc/definitely/not/writable.jsonl"})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(
        Brain(), cfg, [{"token": "t", "role": "admin", "label": "x"}],
        Audit(), QueryLog()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, body = call(srv, "POST", "/search", {"query": "q"})
        assert status == 200
        assert set(body) == {"result", "hits"}
    finally:
        srv.shutdown()


def test_no_log_configured_returns_empty(server):
    srv, _ = server
    _, data = call(srv, "GET", "/queries?limit=5")
    assert data["queries"] == []


def test_limit_is_clamped(server):
    srv, _ = server
    for i in range(3):
        call(srv, "POST", "/search", {"query": f"q{i}"})
    _, data = call(srv, "GET", "/queries?limit=2")
    assert len(data["queries"]) == 2
