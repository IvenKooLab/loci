"""Parse the JSON an LLM was asked for.

Every prompt says "reply with ONLY a JSON array" and the models reply with
a ```json fence or a sentence around it anyway — GLM, DeepSeek and Qwen do
it routinely. json.loads then fails, and at each call site that failure was
swallowed: the feature quietly did nothing (no memory extracted, no query
rewrite, no rerank) or reported itself unavailable (verification).
"""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*[ \t]*\n?(.*?)\n?```", re.S)
_TRAILING_COMMA = re.compile(r",\s*(?=[\]}])")


def _balanced(text: str, open_: str, close: str, start: int) -> str | None:
    """The span from text[start] to its matching `close`, honouring string
    literals; None when it never closes."""
    depth, in_str, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_:
            depth += 1
        elif ch == close:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _candidates(raw: str) -> list[str]:
    """Every complete [...] / {...} span in the reply, longest first."""
    spans = set()
    for open_, close in (("[", "]"), ("{", "}")):
        pos = raw.find(open_)
        while pos != -1:
            span = _balanced(raw, open_, close, pos)
            if span is not None:
                spans.add(span)
            pos = raw.find(open_, pos + 1)
    # longest first: prose like "based on [1] and [2]: [ ... ]" must not
    # yield the citation bracket instead of the payload
    return sorted(spans, key=len, reverse=True)


def parse_json(text, expect=None):
    """Parse `text` as JSON, tolerating code fences, surrounding prose and
    trailing commas.

    `expect` is a type (or tuple of types) the value must be an instance of.
    Returns the value, or None when no complete JSON value of that type can
    be recovered — the caller decides what "nothing" means for its feature."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    fenced = _FENCE.match(raw)
    if fenced:                                   # the whole reply is fenced
        raw = fenced.group(1).strip()
    tried = []
    for cand in [raw, *_candidates(raw)]:
        for variant in (cand, _TRAILING_COMMA.sub("", cand)):
            if variant in tried:
                continue
            tried.append(variant)
            try:
                value = json.loads(variant)
            except json.JSONDecodeError:
                continue
            if expect is None or isinstance(value, expect):
                return value
    return None
