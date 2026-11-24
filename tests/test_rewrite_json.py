"""Query rewriting (--rewrite / multi-query retrieval) reads a JSON array of
variants from the LLM. A fenced reply failed json.loads, the fail-open except
turned that into [query], and the rewrite silently did nothing — the user
paid for an LLM call and got a plain single-query search."""
from __future__ import annotations

from types import SimpleNamespace

import loci.retriever as retriever

LLM = {"base_url": "x", "api_key": "k", "model": "m"}
VARIANTS = '["keyword version", "翻译版本"]'


def _replying(monkeypatch, content):
    reply = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content))])
    # retriever binds OpenAI at import time: patch its own name, or the
    # call goes to the real network
    monkeypatch.setattr(retriever, "OpenAI", lambda **kw: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: reply))))


def test_expand_queries_reads_a_fenced_reply(monkeypatch):
    _replying(monkeypatch, "```json\n" + VARIANTS + "\n```")
    assert retriever.expand_queries(LLM, "q") == ["q", "keyword version", "翻译版本"]


def test_control_plain_reply(monkeypatch):
    _replying(monkeypatch, VARIANTS)
    assert retriever.expand_queries(LLM, "q") == ["q", "keyword version", "翻译版本"]


def test_an_object_reply_falls_back_to_the_plain_query(monkeypatch):
    _replying(monkeypatch, '{"oops": 1}')
    assert retriever.expand_queries(LLM, "q") == ["q"]


def test_a_reply_with_prose_around_it_is_read(monkeypatch):
    _replying(monkeypatch, "Sure! Two variants:\n" + VARIANTS + "\nLet me know.")
    assert len(retriever.expand_queries(LLM, "q")) == 3
