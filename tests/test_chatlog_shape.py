"""A chat export is data that has been re-exported, trimmed by hand and
pushed through other tools. parse_chatlog promised "defensive structure
checks" but only looked at the first element; one conversation that was not
the expected shape — a stray string, a null node, a mapping that is not an
object, a timestamp that is not a number — raised out of the parser, and
since ingest reads the file on every pass, it broke the pass every time.
"""
from __future__ import annotations

import json

from loci import chatlog, loaders


def _turn(role, text, ts=1.0):
    return {"message": {"author": {"role": role}, "create_time": ts,
                        "content": {"content_type": "text", "parts": [text]}}}


GOOD = {"title": "kept", "mapping": {"n": _turn("user", "a real question")}}


def _parse(tmp_path, data, name="conversations.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return chatlog.parse_chatlog(p)


def test_chatgpt_export_survives_elements_that_are_not_conversations(tmp_path):
    data = [GOOD, "garbage", None, 42,
            {"title": "mapping is a string", "mapping": "oops"},
            {"title": "null nodes", "mapping": {"a": None, "b": _turn("assistant", "still readable")}},
            {"title": "message is a string", "mapping": {"a": {"message": "oops"}}},
            {"title": "author is not an object", "mapping": {"a": {"message": {"author": "user", "content": {}}}}},
            {"title": "parts is a number", "mapping": {"a": {"message": {"author": {"role": "user"}, "content": {"parts": 5}}}}}]
    out = _parse(tmp_path, data)
    titles = [c["title"] for c in out]
    assert "kept" in titles
    assert "null nodes" in titles and "still readable" in out[titles.index("null nodes")]["text"]


def test_a_timestamp_that_is_not_a_number_does_not_abort_the_sort(tmp_path):
    data = [{"title": "t", "mapping": {
        "a": {"message": {"author": {"role": "user"}, "create_time": "2024-01-01",
                           "content": {"parts": ["string time"]}}},
        "b": _turn("assistant", "numeric time", 5.0)}}]
    out = _parse(tmp_path, data)
    assert out and "string time" in out[0]["text"] and "numeric time" in out[0]["text"]


def test_the_export_is_recognized_even_when_its_first_element_is_junk(tmp_path):
    out = _parse(tmp_path, ["junk first", GOOD])
    assert out and out[0]["title"] == "kept"


def test_claude_export_survives_malformed_entries(tmp_path):
    data = {"chats": [
        {"name": "good", "chat_messages": [{"sender": "human", "text": "hi"},
                                           {"sender": "assistant", "text": "hello"}]},
        "junk",
        {"name": "messages is an object", "chat_messages": {"a": 1}},
        {"name": "blocks", "chat_messages": [
            "junk",
            {"sender": "human", "content": [{"type": "text", "text": None},
                                            {"type": "text"},
                                            {"type": "text", "text": "kept block"}]}]},
        {"name": "numeric text", "chat_messages": [{"sender": "human", "text": 42}]},
    ]}
    out = _parse(tmp_path, data)
    by_name = {c["title"]: c["text"] for c in out}
    assert "hi" in by_name["good"] and "hello" in by_name["good"]
    assert "kept block" in by_name["blocks"]
    assert "42" in by_name["numeric text"]


def test_ingest_pass_survives_a_damaged_export(tmp_path):
    (tmp_path / "note.md").write_text("# Note\n\nbody", encoding="utf-8")
    (tmp_path / "conversations.json").write_text(json.dumps([GOOD, "garbage"]), encoding="utf-8")
    docs = loaders.scan_sources([{"path": str(tmp_path)}])
    names = sorted(d["path"].replace("\\", "/").rsplit("/", 1)[-1].rsplit("::", 1)[-1] for d in docs)
    assert names == ["kept", "note.md"]             # both the note and the surviving conversation
