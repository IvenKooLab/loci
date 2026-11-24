"""answer verification (--verify) reads a JSON array of claims.

A fenced reply failed json.loads and the user got "(verification
unavailable: JSONDecodeError ...)"; an object instead of an array died as
"AttributeError: 'str' object has no attribute 'get'". Either way the audit
the user explicitly asked for did not happen.
"""
from __future__ import annotations

from types import SimpleNamespace

import loci.retriever as retriever

LLM = {"base_url": "x", "api_key": "k", "model": "m"}
HITS = [{"id": "a", "source": "s.md", "section": "", "text": "irrelevant"},
        {"id": "b", "source": "s.md", "section": "", "text": "directly answers"}]
CLAIMS = '[{"claim": "x", "status": "supported", "excerpts": [1]}]'


def _replying(monkeypatch, content):
    reply = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content))])
    monkeypatch.setattr(retriever, "OpenAI", lambda **kw: SimpleNamespace(   # bound at import
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: reply))))


def test_verify_reads_a_fenced_reply(monkeypatch):
    _replying(monkeypatch, "```json\n" + CLAIMS + "\n```")
    report = retriever.verify_answer(LLM, "q", "answer text", HITS)
    assert "✓ x [excerpt 1]" in report
    assert "unavailable" not in report


def test_control_plain_reply(monkeypatch):
    _replying(monkeypatch, CLAIMS)
    assert "✓ x [excerpt 1]" in retriever.verify_answer(LLM, "q", "answer text", HITS)


def test_an_object_reply_is_reported_as_no_claims_not_as_a_crash(monkeypatch):
    _replying(monkeypatch, '{"claim": "x"}')
    report = retriever.verify_answer(LLM, "q", "answer text", HITS)
    assert "no claims" in report and "AttributeError" not in report


def test_entries_that_are_not_objects_do_not_abort_the_audit(monkeypatch):
    _replying(monkeypatch, '["junk", 7, {"claim": "y", "status": "unsupported"}]')
    report = retriever.verify_answer(LLM, "q", "answer text", HITS)
    assert "✗ y" in report and "junk" not in report
