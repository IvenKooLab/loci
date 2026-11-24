"""Chat-log export loader: turn ChatGPT / Claude exports (both name their file
`conversations.json`) into one virtual markdown document per conversation, so
chat history becomes queryable knowledge with per-conversation citations.

No dependencies — plain json parsing with defensive structure checks."""
from __future__ import annotations

import json
from pathlib import Path

CHATLOG_NAMES = {"conversations.json"}


def parse_chatlog(path: Path) -> list[dict] | None:
    """Return [{title, text}] for ChatGPT/Claude exports, or None if the file
    is not a recognized chat export (callers skip it silently)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(data, list) and data and isinstance(data[0], dict) \
            and "mapping" in data[0]:
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
        title = str(conv.get("title") or "untitled conversation")
        mapping = conv.get("mapping") or {}
        turns = []
        for i, node in enumerate(mapping.values()):
            msg = node.get("message") or {}
            author = (msg.get("author") or {}).get("role", "")
            if author not in ("user", "assistant"):
                continue  # system scaffolding and tool noise
            content = msg.get("content") or {}
            if content.get("content_type") not in (None, "text"):
                continue
            parts = [p for p in (content.get("parts") or [])
                     if isinstance(p, str) and p.strip()]
            if not parts:
                continue
            turns.append((msg.get("create_time"), i,
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
        title = str(conv.get("name") or "untitled conversation")
        turns = []
        for msg in conv.get("chat_messages") or []:
            sender = str(msg.get("sender", ""))
            role = "user" if sender == "human" else sender
            text = msg.get("text")
            if not text and isinstance(msg.get("content"), list):
                text = "\n".join(c.get("text", "") for c in msg["content"]
                                 if isinstance(c, dict) and c.get("type") == "text")
            if not text:
                continue
            turns.append((msg.get("created_at") or "", _turn(role, str(text))))
        turns.sort(key=lambda t: t[0])
        if turns:
            out.append({"title": title,
                        "text": f"# {title}\n\n" + "\n\n".join(t[1] for t in turns)})
    return out
