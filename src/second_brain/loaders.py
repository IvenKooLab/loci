"""文档加载：递归扫描目录，读取 .md/.txt。"""
from __future__ import annotations

import hashlib
from pathlib import Path

SUFFIXES = {".md", ".txt"}


def file_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def scan_sources(sources: list[dict]) -> list[dict]:
    """返回 [{path, content, hash}]，path 为绝对路径字符串。"""
    docs, seen = [], set()
    for src in sources:
        root = Path(src["path"]).expanduser()
        if not root.exists():
            print(f"[warn] 目录不存在，跳过: {root}")
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
                print(f"[warn] 非 UTF-8，跳过: {p.name}")
                continue
            if content.strip():
                docs.append({"path": ap, "content": content, "hash": file_hash(content)})
    return docs
