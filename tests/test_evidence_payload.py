"""The console's evidence pane rides on `/search` returning its hits.

Two contracts matter here and both are easy to break by accident:

1. `result` stays byte-identical — scripts and older console builds read the
   text, and nothing about adding the pane may change it.
2. `hits` is additive and carries the *full* chunk text (the text view keeps
   truncating at 500 chars), because the whole point is showing the passage.
"""
from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from loci.http_api import Audit, _make_handler
from loci.mcp_server import Brain

HITS = [
    {"id": "a1", "source": "projects/aurora/decisions.md",
     "section": "ADR-001: SHT45 over BME280", "text": "x" * 700,
     "tags": "aurora,hardware", "distance": 0.0},
    {"id": "b2", "source": "notes/antenna-notes.md", "section": "",
     "text": "wifi retries", "tags": "", "distance": 0.42},
]


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = 0

    def search(self, query, **kwargs):
        self.calls += 1
        return self.hits


def make_brain(hits):
    brain = Brain()
    brain._retriever = FakeRetriever(hits)   # skip _ensure: no config, no network
    brain._cfg = None
    return brain


def legacy_text(hits):
    blocks = []
    for i, h in enumerate(hits, 1):
        where = h["source"] + (f" > {h['section']}" if h["section"] else "")
        blocks.append(f"[{i}] {where}\n{h['text'][:500]}")
    return "\n\n".join(blocks) or "(no results)"


def test_result_text_is_unchanged():
    brain = make_brain(HITS)
    assert brain.search("sensor") == legacy_text(HITS)


def test_payload_returns_full_text_and_slim_hits():
    payload = make_brain(HITS).search_payload("sensor")
    assert payload["result"] == legacy_text(HITS)
    assert len(payload["hits"]) == 2
    assert payload["hits"][0]["text"] == HITS[0]["text"]      # not truncated
    assert set(payload["hits"][0]) == {"source", "section", "text",
                                       "tags", "distance"}


def test_payload_retrieves_once():
    brain = make_brain(HITS)
    brain.search_payload("sensor")
    assert brain._retriever.calls == 1


def test_empty_and_blank_queries():
    brain = make_brain([])
    assert brain.search_payload("sensor") == {"result": "(no results)", "hits": []}
    blank = make_brain(HITS).search_payload("   ")
    assert blank["hits"] == []
    assert "empty query" in blank["result"]


@pytest.fixture
def server():
    cfg = SimpleNamespace(memories={"path": "/tmp"},
                          http={"icons": "/tmp", "local_admin": False})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(
        make_brain(HITS), cfg,
        [{"token": "t", "role": "admin", "label": "test"}], Audit()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def post(server, path, body, token="t"):
    conn = http.client.HTTPConnection(*server.server_address, timeout=4)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("POST", path, body=json.dumps(body), headers=headers)
    res = conn.getresponse()
    return res.status, json.loads(res.read() or b"{}")


def test_http_search_adds_hits_without_touching_result(server):
    status, data = post(server, "/search", {"query": "sensor"})
    assert status == 200
    assert data["result"] == legacy_text(HITS)
    assert [h["source"] for h in data["hits"]] == [
        "projects/aurora/decisions.md", "notes/antenna-notes.md"]


def test_http_search_is_still_authorized(server):
    status, _ = post(server, "/search", {"query": "sensor"}, token=None)
    assert status == 401
