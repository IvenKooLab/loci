import json

from second_brain.chatlog import parse_chatlog
from second_brain.loaders import scan_sources

CHATGPT_EXPORT = [
    {"title": "RAG design", "create_time": 1700000000,
     "mapping": {
         "n1": {"message": {"author": {"role": "system"},
                            "content": {"content_type": "text", "parts": ["You are..."]}}},
         "n2": {"message": {"author": {"role": "user"},
                            "create_time": 1700000001,
                            "content": {"content_type": "text", "parts": ["how do I chunk?"]}}},
         "n3": {"message": {"author": {"role": "assistant"},
                            "create_time": 1700000002,
                            "content": {"content_type": "text",
                                        "parts": ["Split by headings.", "Use overlap."]}}},
         "n4": {"message": {"author": {"role": "tool"},
                            "content": {"content_type": "text", "parts": ["noise"]}}},
     }},
    {"title": "empty conv", "mapping": {}},
]

CLAUDE_EXPORT = {"chats": [
    {"name": "-vector db-",
     "chat_messages": [
         {"sender": "human", "created_at": "2026-01-01T00:00:00Z",
          "text": "chroma vs faiss?"},
         {"sender": "assistant", "created_at": "2026-01-01T00:01:00Z",
          "content": [{"type": "text", "text": "chroma for simplicity."},
                      {"type": "tool_use", "text": "ignored"}]},
     ]},
]}


def write(tmp_path, payload):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_parse_chatgpt_orders_turns_and_drops_noise(tmp_path):
    out = parse_chatlog(write(tmp_path, CHATGPT_EXPORT))
    assert out is not None and len(out) == 1  # empty conv dropped
    text = out[0]["text"]
    assert text.startswith("# RAG design")
    assert text.index("**user**") < text.index("**assistant**")
    assert "noise" not in text and "You are..." not in text
    assert "Use overlap." in text


def test_parse_claude_handles_text_and_content_blocks(tmp_path):
    out = parse_chatlog(write(tmp_path, CLAUDE_EXPORT))
    assert out is not None and len(out) == 1
    assert out[0]["title"] == "-vector db-"
    assert "chroma vs faiss?" in out[0]["text"]
    assert "chroma for simplicity." in out[0]["text"]
    assert "ignored" not in out[0]["text"]


def test_unknown_json_returns_none(tmp_path):
    assert parse_chatlog(write(tmp_path, [{"foo": 1}])) is None
    assert parse_chatlog(write(tmp_path, {"hello": "world"})) is None


def test_malformed_json_returns_none(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text("{not json", encoding="utf-8")
    assert parse_chatlog(p) is None


def test_scan_sources_expands_chatlog_into_virtual_docs(tmp_path):
    write(tmp_path, CHATGPT_EXPORT)
    docs = scan_sources([{"path": str(tmp_path)}])
    assert len(docs) == 1
    d = docs[0]
    assert d["tags"] == "chatlog"
    assert d["path"].endswith("::RAG design")
    assert d["content"].startswith("# RAG design")


def test_plain_json_files_are_not_touched(tmp_path):
    (tmp_path / "data.json").write_text('{"any": "json"}', encoding="utf-8")
    assert scan_sources([{"path": str(tmp_path)}]) == []
