"""LLM replies are JSON "only when asked" — recover the payload anyway.

Each feature has a control (plain JSON, which always worked) and the shapes
models actually send: a ```json fence, prose around the payload, trailing
commas. Before this every one of the fenced cases failed silently.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import loci.memories as memories
import openai
from loci.llm_json import parse_json

PAYLOAD = '[{"title": "Blue-green", "text": "Deploys go blue-green."}]'


# ---------- the parser ----------
@pytest.mark.parametrize("reply", [
    PAYLOAD,                                                   # control
    "```json\n" + PAYLOAD + "\n```",                           # fenced
    "```\n" + PAYLOAD + "\n```",                               # fenced, no language
    "Here is what is worth remembering:\n" + PAYLOAD,          # prose before
    PAYLOAD + "\n\nHope this helps!",                          # prose after
    "```JSON\n" + PAYLOAD + "\n```\nDone.",
])
def test_payload_is_recovered_from_every_common_shape(reply):
    assert parse_json(reply, expect=list) == [{"title": "Blue-green", "text": "Deploys go blue-green."}]


def test_trailing_commas_are_tolerated():
    assert parse_json('```json\n[{"a": 1,}, {"b": [1, 2,],},]\n```', expect=list) == \
        [{"a": 1}, {"b": [1, 2]}]


def test_brackets_inside_strings_do_not_confuse_the_span_search():
    reply = 'Result: [{"text": "call f(x[0]) then } else {", "n": 1}]'
    assert parse_json(reply, expect=list) == [{"text": "call f(x[0]) then } else {", "n": 1}]


def test_citation_brackets_in_prose_do_not_win_over_the_payload():
    reply = "Based on [1] and [2]: " + PAYLOAD
    assert parse_json(reply, expect=list)[0]["title"] == "Blue-green"


def test_an_object_is_returned_when_an_object_is_expected():
    assert parse_json('```json\n{"ok": true}\n```', expect=dict) == {"ok": True}


def test_a_reply_of_the_wrong_shape_yields_none():
    assert parse_json('{"claim": "x"}', expect=list) is None   # object, not array
    assert parse_json("[1, 2]", expect=dict) is None
    assert parse_json("no json at all here [unclosed", expect=list) is None
    assert parse_json("", expect=list) is None
    assert parse_json(None, expect=list) is None
    assert parse_json("[1,]", expect=list) == [1]               # a trailing comma is recoverable


def test_bare_scalars_are_parsed_when_no_type_is_expected():
    assert parse_json("```json\n42\n```") == 42


# ---------- memories.extract_memories ----------
def _replying(content):
    """openai.OpenAI is imported inside extract_memories, so patching the
    module attribute is enough — and a control proves the patch took."""
    reply = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content))])
    return lambda **kw: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **_: reply)))


LLM = {"base_url": "x", "api_key": "k", "model": "m"}


def test_extract_memories_reads_a_fenced_reply(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", _replying("```json\n" + PAYLOAD + "\n```"))
    items = memories.extract_memories(LLM, "User: how do we deploy?\nAssistant: blue-green.")
    assert [it["text"] for it in items] == ["Deploys go blue-green."]
    assert items[0]["title"] == "Blue-green"


def test_extract_memories_control_plain_reply(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", _replying(PAYLOAD))
    assert len(memories.extract_memories(LLM, "t")) == 1


def test_one_malformed_item_does_not_cost_the_whole_batch(monkeypatch):
    reply = '[{"title": "ok", "text": "a real fact"}, {"title": "x", "text": 42}, "junk", {"title": "no text"}]'
    monkeypatch.setattr(openai, "OpenAI", _replying(reply))
    items = memories.extract_memories(LLM, "t")
    assert [it["text"] for it in items] == ["a real fact"]


def test_nothing_rememberable_yields_nothing(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", _replying("```json\n[]\n```"))
    assert memories.extract_memories(LLM, "small talk") == []
