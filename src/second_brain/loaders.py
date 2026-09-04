"""Document loading: recursively scan directories for .md/.txt files,
peel off Obsidian-style YAML frontmatter (tags/aliases subset)."""
from __future__ import annotations

import hashlib
from pathlib import Path

SUFFIXES = {".md", ".txt"}


def file_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse a minimal YAML subset from leading --- fences: scalars and lists.
    Returns ({meta}, body); malformed fences are left in the body untouched."""
    if not content.startswith("---"):
        return {}, content
    lines = content.splitlines()
    if lines[0].strip() != "---":
        return {}, content
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, content
    meta: dict = {}
    current_list: str | None = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list:
            meta[current_list].append(stripped[2:].strip().strip('"\''))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        current_list = None
        if not value:
            meta[key] = []
            current_list = key
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [v.strip().strip("\"'") for v in inner.split(",")] if inner else []
        else:
            meta[key] = value.strip("\"'")
    return meta, "\n".join(lines[end + 1:])


def tags_of(meta: dict) -> str:
    """Normalize the frontmatter `tags` key (list or string) to a comma-joined string."""
    raw = meta.get("tags", [])
    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",")]
    else:
        items = [str(t).strip() for t in raw]
    return ",".join(t for t in items if t)


def scan_sources(sources: list[dict]) -> list[dict]:
    """Return [{path, content, hash, tags}] with absolute path strings."""
    docs, seen = [], set()
    for src in sources:
        root = Path(src["path"]).expanduser()
        if not root.exists():
            print(f"[warn] directory not found, skipping: {root}")
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in SUFFIXES:
                continue
            ap = str(p.resolve())
            if ap in seen:
                continue
            seen.add(ap)
            try:
                raw = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                print(f"[warn] not UTF-8, skipping: {p.name}")
                continue
            if not raw.strip():
                continue
            meta, body = parse_frontmatter(raw)
            docs.append({"path": ap, "content": body, "hash": file_hash(raw),
                         "tags": tags_of(meta)})
    return docs
