"""Document loading: recursively scan directories for .md/.txt files."""
from __future__ import annotations

import hashlib
from pathlib import Path

SUFFIXES = {".md", ".txt"}


def file_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def scan_sources(sources: list[dict]) -> list[dict]:
    """Return [{path, content, hash}] with absolute path strings."""
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
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                print(f"[warn] not UTF-8, skipping: {p.name}")
                continue
            if content.strip():
                docs.append({"path": ap, "content": content, "hash": file_hash(content)})
    return docs
