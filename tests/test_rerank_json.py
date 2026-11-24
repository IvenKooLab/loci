"""LLM reranking (--rerank) reads [[index, score], ...] from the model.

A fenced reply failed json.loads and the fail-open except kept the fused
order: the rerank call was made, paid for, and its verdict thrown away —
the user asked for reranking and silently got none.
"""
from __future__ import annotations

from types import SimpleNamespace

import loci.retriever as retriever

LLM = {"base_url": "x", "api_key": "k", "model": "m"}
HITS = [{"id": "a", "source": "s.md", "section": "", "text": "irrelevant"},
        {"id": "b", "source": "s.md", "section": "", "text": "directly answers"}]
PAIRS = "[[0, 0], [1, 3]]"


def _replying(monkeypatch, content):
    reply = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content))])
    monkeypatch.setattr(retriever, "OpenAI", lambda **kw: SimpleNamespace(   # bound at import
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: reply))))


def test_rerank_reads_a_fenced_reply(monkeypatch):
    _replying(monkeypatch, "```json\n" + PAIRS + "\n```")
    assert [h["id"] for h in retriever.rerank_hits(LLM, "q", HITS)] == ["b", "a"]


def test_control_plain_reply(monkeypatch):
    _replying(monkeypatch, PAIRS)
    assert [h["id"] for h in retriever.rerank_hits(LLM, "q", HITS)] == ["b", "a"]


def test_garbage_keeps_the_fused_order(monkeypatch):
    _replying(monkeypatch, "sorry, I cannot rank these")
    assert [h["id"] for h in retriever.rerank_hits(LLM, "q", HITS)] == ["a", "b"]


def test_a_reply_that_is_not_a_list_of_pairs_keeps_the_fused_order(monkeypatch):
    _replying(monkeypatch, "[1, 2]")
    assert [h["id"] for h in retriever.rerank_hits(LLM, "q", HITS)] == ["a", "b"]


def test_one_malformed_pair_does_not_cost_the_others(monkeypatch):
    _replying(monkeypatch, '[[0, 0], "junk", [1, 3], [9]]')
    assert [h["id"] for h in retriever.rerank_hits(LLM, "q", HITS)] == ["b", "a"]
