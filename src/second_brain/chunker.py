"""Chunking: split markdown along headings; fenced code blocks stay intact;
oversized prose falls back to a sliding window. Chunks carry a heading
breadcrumb so citations can point at a section, not just a file."""
from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
_FENCE = re.compile(r"^\s*```")


def split_markdown(text: str, size: int, overlap: int) -> list[dict]:
    """Return [{"text", "section"}] where section is a heading breadcrumb like
    "Install > Prerequisites" ("" for text before any heading)."""
    out: list[dict] = []
    for crumb, block in _blocks_with_breadcrumbs(text):
        block = block.strip()
        if not block:
            continue
        if len(block) <= size:
            out.append({"text": block, "section": crumb})
            continue
        for seg, is_code in _split_around_code(block):
            seg = seg.strip()
            if not seg:
                continue
            if is_code or len(seg) <= size:
                # never slice inside a fenced block, even if it overflows `size`
                out.append({"text": seg, "section": crumb})
            else:
                out.extend({"text": piece, "section": crumb}
                           for piece in _sliding_window(seg, size, overlap))
    return [c for c in out if len(c["text"]) >= 30]  # drop tiny fragments


def _blocks_with_breadcrumbs(text: str) -> list[tuple[str, str]]:
    """Split into (breadcrumb, block) pairs at headings; blocks keep their heading line."""
    stack: dict[int, str] = {}  # heading level -> title
    blocks: list[tuple[str, str]] = []
    crumb = ""
    lines: list[str] = []

    def flush() -> None:
        if lines and "\n".join(lines).strip():
            blocks.append((crumb, "\n".join(lines)))

    for line in text.splitlines():
        m = _HEADING.match(line)
        if not m:
            lines.append(line)
            continue
        flush()
        level, title = len(m.group(1)), m.group(2).strip()
        stack[level] = title
        for lvl in [l for l in stack if l > level]:
            del stack[lvl]
        crumb = " > ".join(stack[lvl] for lvl in sorted(stack))
        lines = [line]
    flush()
    return blocks


def _split_around_code(block: str) -> list[tuple[str, bool]]:
    """Split a block into (segment, is_code) pieces along ``` fences.
    An unclosed fence treats the rest of the block as code (safe default)."""
    segments: list[tuple[str, bool]] = []
    prose: list[str] = []
    code: list[str] = []
    in_code = False
    for line in block.splitlines():
        if _FENCE.match(line):
            if in_code:
                code.append(line)
                segments.append(("\n".join(code), True))
                code = []
                in_code = False
            else:
                if "\n".join(prose).strip():
                    segments.append(("\n".join(prose), False))
                prose = []
                in_code = True
                code = [line]
        elif in_code:
            code.append(line)
        else:
            prose.append(line)
    if in_code:
        segments.append(("\n".join(code), True))
    elif "\n".join(prose).strip():
        segments.append(("\n".join(prose), False))
    return segments


def _sliding_window(text: str, size: int, overlap: int) -> list[str]:
    step = max(size - overlap, 1)
    return [text[i:i + size] for i in range(0, len(text), step)]
