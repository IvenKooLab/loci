"""Blank input over MCP/HTTP must be answered, not sent to the provider.

`loci ask ""` and `loci search ""` reject a blank query before any work
(the CLI guard), and search_payload does the same for MCP/HTTP — but
Brain.ask and Brain.wiki passed theirs straight through: the empty string
reached the embedding endpoint and came back as a raw provider 400, which
the tool caller saw as an exception. A `k` that is not an int (hosts do not
all validate the schema) crashed the same way further in.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from loci.mcp_server import Brain

HIT = {"id": "a", "source": "s.md", "section": "", "text": "hit text",
       "tags": "", "links": "", "mtime": 0.0, "distance": 0.1}


class _Retriever:
    """Records the query; raises the way an embedding provider answers ""."""

    def __init__(self):
        self.queries = []

    def search(self, q, **kw):
        self.queries.append(q)
        if not str(q).strip():
            raise RuntimeError("provider 400 for empty input")
        return [dict(HIT)]


def _brain(retriever):
    brain = Brain.__new__(Brain)              # no config/network in __init__
    brain._cfg = SimpleNamespace(sources=[], memories={"path": ""}, llm={})
    brain._retriever, brain._store = retriever, None
    brain._config_error = None
    brain._lock = threading.RLock()
    return brain


@pytest.mark.parametrize("question", ["", "   ", "\n\t", None])
def test_blank_ask_is_answered_before_retrieval(question):
    r = _Retriever()
    reply = _brain(r).ask(question)
    assert "empty question" in reply
    assert r.queries == []                    # nothing reached the provider


def test_wiki_refuses_a_blank_topic_before_retrieval():
    r = _Retriever()
    reply = _brain(r).wiki("  ")
    assert "empty topic" in reply
    assert r.queries == []


@pytest.mark.parametrize("given, expected", [("5", 5), ("many", 12), ([3], 12), (None, 12)])
def test_k_on_wiki_is_coerced_or_falls_back_to_the_default(monkeypatch, given, expected):
    r = _Retriever()
    seen = {}

    def fake_page(cfg, topic, k=12):
        seen["k"] = k
        return {"path": "p.md", "chunks": 1, "sources": 1, "topic": topic}

    import loci.wiki
    monkeypatch.setattr(loci.wiki, "generate_wiki_page", fake_page)
    reply = _brain(r).wiki("deploy policy", k=given)
    assert seen["k"] == expected and "wiki page written" in reply
