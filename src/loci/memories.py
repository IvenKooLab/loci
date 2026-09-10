"""Cross-session memory: agents (and humans) store durable notes as markdown
files in a memories directory. Files are first-class index citizens — once
written they are ingested like any other source, so every MCP host that mounts
loci shares the same memory.

Write path is always safe (plain markdown, atomic); embedding/indexing is
best-effort and can be replayed with `loci ingest` at any time."""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

_MEMORY_TAG = "memory"


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", title.strip()).strip("-").lower()
    return slug[:48] or "memory"


def write_memory(mem_dir: str, text: str, title: str | None = None,
                 tags: list[str] | None = None) -> str:
    """Write one memory note; returns the absolute file path."""
    d = Path(mem_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    title = (title or text.strip().splitlines()[0] or "memory").strip()[:80]
    ts = datetime.now()
    base = f"{ts.strftime('%Y%m%d-%H%M%S')}-{slugify(title)}"
    path = d / f"{base}.md"
    n = 2
    while path.exists():                       # two IDEs writing in the same second
        path = d / f"{base}-{n}.md"
        n += 1
    tag_list = [_MEMORY_TAG] + [t.strip() for t in (tags or []) if t.strip()]
    iso = ts.strftime("%Y-%m-%d %H:%M")
    front = ("---\n"
             f"tags: [{', '.join(tag_list)}]\n"
             f"created: {iso}\n"
             f"title: {title}\n"
             "---\n")
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(f"{front}# {title}\n\n{text.strip()}\n", encoding="utf-8")
    tmp.rename(path)                           # atomic on same filesystem
    return str(path.resolve())


def find_memories(mem_dir: str, query: str) -> list[Path]:
    """Memory files whose filename or content mentions query (newest first)."""
    d = Path(mem_dir).expanduser()
    if not d.exists():
        return []
    q = query.lower()
    hits = [p for p in d.glob("*.md")
            if q in p.stem.lower() or q in p.read_text(encoding="utf-8", errors="ignore").lower()]
    return sorted(hits, key=lambda p: p.name, reverse=True)


def forget_memory(mem_dir: str, query: str) -> list[str]:
    """Soft-delete matching memories into <mem_dir>/.trash. Returns moved paths."""
    d = Path(mem_dir).expanduser()
    trash = d / ".trash"
    moved = []
    for p in find_memories(mem_dir, query):
        trash.mkdir(parents=True, exist_ok=True)
        dest = trash / p.name
        n = 2
        while dest.exists():
            dest = trash / f"{p.stem}-{n}{p.suffix}"
            n += 1
        shutil.move(str(p), str(dest))
        moved.append(str(dest))
    return moved


def index_memory_file(cfg, path: str) -> int:
    """Embed + upsert one memory file into the index immediately.
    Returns chunk count; raises on embedder/store errors (caller decides)."""
    from loci import chunker, loaders
    from loci.cli import build

    embedder, store = build(cfg)
    raw = Path(path).read_text(encoding="utf-8")
    meta, body = loaders.parse_frontmatter(raw)
    chunks = chunker.split_markdown(body, cfg.chunk["size"], cfg.chunk["overlap"])
    if not chunks:
        return 0
    vectors = embedder.embed([c["text"] for c in chunks])
    store.upsert_chunks(chunks, vectors, str(Path(path).resolve()),
                        loaders.file_hash(raw), loaders.tags_of(meta), "", Path(path).stat().st_mtime)
    return len(chunks)
