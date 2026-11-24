"""Chat-log export loader: turn ChatGPT / Claude exports (both name their file
`conversations.json`) into one virtual markdown document per conversation, so
chat history becomes queryable knowledge with per-conversation citations.

No dependencies — plain json parsing with defensive structure checks."""
from __future__ import annotations

import json
from pathlib import Path

CHATLOG_NAMES = {"conversations.json"}


def _obj(value) -> dict:
    """`value` when it is an object, else an empty one."""
    return value if isinstance(value, dict) else {}


def _time(value):
    """A sortable timestamp, or None when it is not a number.

    An export is re-exported, trimmed by hand and pushed through other
    tools: a create_time that arrived as a date string raised TypeError out
    of the sort and cost the whole file."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_chatlog(path: Path) -> list[dict] | None:
    """Return [{title, text}] for ChatGPT/Claude exports, or None if the file
    is not a recognized chat export (callers skip it silently)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    # any element may identify the format: looking only at the first one
    # made a stray leading string turn a real export into "unrecognized"
    if isinstance(data, list) and any("mapping" in _obj(item) for item in data):
        return _parse_chatgpt(data)
    if isinstance(data, dict) and isinstance(data.get("chats"), list):
        return _parse_claude(data["chats"])
    return None


def _turn(role: str, text: str) -> str:
    role = {"user": "user", "assistant": "assistant"}.get(role, role)
    return f"**{role}**: {text.strip()}" if text.strip() else ""


def _parse_chatgpt(data: list) -> list[dict]:
    out = []
    for conv in data:
        # one element that is not the expected shape must not cost the other
        # conversations — ingest reads this file on every pass
        conv = _obj(conv)
        title = str(conv.get("title") or "untitled conversation")
        mapping = _obj(conv.get("mapping"))
        turns = []
        for i, node in enumerate(mapping.values()):
            msg = _obj(_obj(node).get("message"))
            author = _obj(msg.get("author")).get("role", "")
            if author not in ("user", "assistant"):
                continue  # system scaffolding and tool noise
            content = _obj(msg.get("content"))
            if content.get("content_type") not in (None, "text"):
                continue
            raw_parts = content.get("parts")
            parts = [p for p in (raw_parts if isinstance(raw_parts, (list, tuple)) else [])
                     if isinstance(p, str) and p.strip()]
            if not parts:
                continue
            turns.append((_time(msg.get("create_time")), i,
                          _turn(author, "\n".join(parts))))
        # An untimed turn keeps its place: it takes the time of the turn
        # before it (in mapping order), so with the mapping index as the
        # tiebreaker it sorts right after that turn. Sorting it as time 0
        # hoisted every untimed turn above the whole conversation — in the
        # common export, where user turns carry no create_time, a
        # q1/a1/q2/a2 conversation read as q1 q2 a1 a2.
        turns.sort(key=lambda t: t[1])
        carry = float("-inf")
        for n, (ts, i, text) in enumerate(turns):
            if ts is None:
                turns[n] = (carry, i, text)
            else:
                carry = ts
        turns.sort(key=lambda t: (t[0], t[1]))
        if turns:
            out.append({"title": title,
                        "text": f"# {title}\n\n" + "\n\n".join(t[2] for t in turns)})
    return out


def _parse_claude(chats: list) -> list[dict]:
    out = []
    for conv in chats:
        conv = _obj(conv)
        title = str(conv.get("name") or "untitled conversation")
        turns = []
        messages = conv.get("chat_messages") or []
        for msg in (messages if isinstance(messages, list) else []):
            msg = _obj(msg)
            sender = str(msg.get("sender", ""))
            role = "user" if sender == "human" else sender
            text = msg.get("text")
            blocks = msg.get("content")
            if not text and isinstance(blocks, list):
                text = "\n".join(str(_obj(block).get("text") or "") for block in blocks
                                 if isinstance(block, dict) and block.get("type") == "text")
            if not text:
                continue
            created = msg.get("created_at")
            turns.append((str(created) if created is not None else "", _turn(role, str(text))))
        turns.sort(key=lambda t: t[0])
        if turns:
            out.append({"title": title,
                        "text": f"# {title}\n\n" + "\n\n".join(t[1] for t in turns)})
    return out
