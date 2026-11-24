"""Cross-session memory: agents (and humans) store durable notes as markdown
files in a memories directory. Files are first-class index citizens — once
written they are ingested like any other source, so every MCP host that mounts
loci shares the same memory.

Write path is always safe (plain markdown, atomic); embedding/indexing is
best-effort and can be replayed with `loci ingest` at any time."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

_MEMORY_TAG = "memory"

# A value YAML reads back unchanged without quotes: one line, and none of
# the characters that open a comment, a list, an anchor or a key.
_PLAIN_SAFE = re.compile(r"""^[^\s"'\[\]{}#&*!|>%@`:,?~-][^"'\[\]{}#&*!|>%@`:,]*$""")
_YAML_WORDS = {"true", "false", "null", "yes", "no", "on", "off"}


def frontmatter_scalar(value) -> str:
    """`value` as a frontmatter scalar that reads back as exactly `value`.

    Tags and titles are caller input (JSON from MCP hosts and the console)
    and used to be spliced in bare: a tag with a comma, bracket or newline
    broke the whole tag list, a title with ` #` was cut off at the hash (a
    YAML comment), and a newline in a title ended the frontmatter early —
    `title: "x\\n---\\ninjected: true"` wrote a key nobody sent.

    Plain when plainly safe; single-quoted when it holds double quotes
    (`'Say "hi"'`); double-quoted otherwise. Always one line."""
    value = " ".join(str(value).split())
    if not value:
        return '""'
    if _PLAIN_SAFE.match(value) and value.lower() not in _YAML_WORDS:
        return value
    if '"' not in value:
        return json.dumps(value, ensure_ascii=False)
    if "'" not in value:
        return "'" + value + "'"
    return json.dumps(value, ensure_ascii=False)


def _tag_text(tag) -> str:
    """A tag as loci can carry it: one line, no commas (they separate the
    tags once a list is joined for the index), at most 60 characters."""
    text = " ".join(str(tag).split()).replace(",", " ")
    return " ".join(text.split())[:60].strip()


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", title.strip()).strip("-").lower()
    return slug[:48] or "memory"


def write_memory(mem_dir: str, text: str, title: str | None = None,
                 tags: list[str] | None = None) -> str:
    """Write one memory note; returns the absolute file path."""
    d = Path(mem_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    if not isinstance(text, str):
        # callers pass JSON: a number or object is stored in text form
        # rather than refused with an AttributeError
        text = json.dumps(text, ensure_ascii=False) if isinstance(text, (dict, list)) \
            else str(text)
    # A blank body has no first line to title itself from (an empty remember
    # used to die on splitlines()[0]). The hashes are dropped: a body that
    # opens with "# Heading" titled the note "# Heading", and
    # `title: # Heading` reads back as no title at all (a YAML comment).
    first_line = text.strip().splitlines()[0].lstrip("#").strip() if text.strip() else ""
    explicit = "" if title is None else str(title).strip()
    title = " ".join((explicit or first_line or "memory").split())[:80].strip()
    ts = datetime.now()
    base = f"{ts.strftime('%Y%m%d-%H%M%S')}-{slugify(title)}"
    # claim the name atomically (O_CREAT|O_EXCL): a check-then-create window
    # let two writers in the same second pick the same path and one overwrite
    # the other — 80 concurrent remembers used to leave 79 notes
    path = d / f"{base}.md"
    n = 2
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:                # two IDEs writing in the same second
            path = d / f"{base}-{n}.md"
            n += 1
    os.close(fd)
    # callers (HTTP/MCP) pass user JSON: coerce each tag — an int/None item
    # used to crash the whole write, a bare string was iterated per character
    if tags is None:
        raw_tags: list = []
    elif isinstance(tags, str):
        raw_tags = tags.split(",")             # "rag, system": hosts do not all validate the schema
    elif isinstance(tags, (list, tuple, set)):
        raw_tags = list(tags)
    else:
        raw_tags = [tags]
    tag_list = [_MEMORY_TAG] + [t for t in (_tag_text(tag) for tag in raw_tags
                                             if tag is not None) if t]
    iso = ts.strftime("%Y-%m-%d %H:%M")
    front = ("---\n"
             f"tags: [{', '.join(frontmatter_scalar(t) for t in tag_list)}]\n"
             f"created: {iso}\n"
             f"title: {frontmatter_scalar(title)}\n"
             "---\n")
    tmp = path.with_suffix(f".md.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(f"{front}# {title}\n\n{text.strip()}\n", encoding="utf-8")
    tmp.replace(path)                          # atomic + overwrites on Windows
    return str(path.resolve())


EXTRACT_PROMPT = (
    "Review the conversation below and extract 0-3 durable facts worth remembering "
    "long-term (decisions, preferences, facts about projects, lessons learned). "
    "Do NOT extract ephemeral details, small talk, or anything already obvious. "
    'Reply with ONLY a JSON array like [{"title": "short title", "text": "one-sentence fact"}]. '
    "Return [] if nothing is worth remembering."
)


def extract_memories(llm_cfg: dict, transcript: str) -> list[dict]:
    """LLM extracts salient facts from a conversation. Fail-open, max 3."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
        resp = client.chat.completions.create(
            model=llm_cfg["model"],
            messages=[
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": transcript[-2000:]},
            ],
            temperature=0.0,
        )
        # models routinely wrap the array in a ```json fence; a plain
        # json.loads then failed, was swallowed below, and chat remembered
        # nothing at all without saying so
        from loci.llm_json import parse_json
        items = parse_json(resp.choices[0].message.content, expect=list) or []
        out = []
        for it in items:
            # one item with a non-string text used to cost the whole batch
            if not isinstance(it, dict) or not isinstance(it.get("text"), str) \
                    or not it["text"].strip():
                continue
            title = it.get("title")
            out.append({"title": title.strip() if isinstance(title, str) and title.strip() else None,
                        "text": it["text"].strip()})
        return out[:3]
    except Exception:
        return []


def find_memories(mem_dir: str, query: str) -> list[Path]:
    """Memory files whose filename or content mentions query (newest first).
    `._*` AppleDouble sidecars (Finder artifacts on exFAT/network copies)
    are skipped — they are binary, not memories."""
    d = Path(mem_dir).expanduser()
    if not d.exists():
        return []
    q = query.lower()
    hits = [p for p in d.glob("*.md")
            if not p.name.startswith("._")
            and (q in p.stem.lower()
                 or q in p.read_text(encoding="utf-8", errors="ignore").lower())]
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


def index_document_file(cfg, path: str) -> int:
    """Index ONE arbitrary document (md/txt/pdf/docx/html/org) into the index.

    This is the entry point behind the console's upload: a dropped file becomes
    searchable without adding a [[sources]] directory or running a full ingest.
    Reuses identical chunks on re-upload (the same content-hash path `ingest`
    uses), so replacing a file does not re-embed what did not change.
    """
    from pathlib import Path as _P

    from loci import loaders
    from loci.cli import build

    p = _P(path).expanduser().resolve()
    doc = loaders.load_one(p, cfg.chunk["size"], cfg.chunk["overlap"])
    if doc is None:
        raise ValueError(f"unsupported or empty file: {p.name}")
    from loci import chunker
    chunks = chunker.split_markdown(doc["content"], doc["chunk_size"],
                                    doc["chunk_overlap"])
    if not chunks:
        raise ValueError(f"no indexable text in {p.name}")
    embedder, store = build(cfg)
    _ensure_vector_space(embedder, store, cfg)
    texts = [c["text"] for c in chunks]
    chashes, reuse = store.reuse_map(doc["path"], texts)
    missing = [i for i, h in enumerate(chashes) if h not in reuse]
    new_vecs = embedder.embed([texts[i] for i in missing]) if missing else []
    vectors: list = [None] * len(chunks)
    for i, h in enumerate(chashes):
        if h in reuse:
            vectors[i] = reuse[h]
    for i, v in zip(missing, new_vecs):
        vectors[i] = v
    store.upsert_chunks(chunks, vectors, doc["path"], doc["hash"],
                        doc["tags"], doc["links"], doc["mtime"], chashes=chashes)
    return len(chunks)


def _ensure_vector_space(embedder, store, cfg) -> None:
    """One cheap embed call before any write: refuse (SystemExit with the
    standard --force guidance) when the configured embedding model no longer
    matches the collection. Every immediate-index write path goes through
    this — remember, chat auto-extract, harness summaries, uploads — so a
    model switch surfaces as actionable guidance instead of a raw chroma
    dimension error (uploads used to *delete the user's file* on it)."""
    probe = embedder.embed(["dimension probe"])
    store.ensure_embed(cfg.embed["model"], len(probe[0]), rebuild=False)


def index_memory_file(cfg, path: str) -> int:
    """Embed + upsert one memory file into the index immediately.
    Returns chunk count; raises on embedder/store errors (caller decides)."""
    from loci import chunker, loaders
    from loci.cli import build

    embedder, store = build(cfg)
    _ensure_vector_space(embedder, store, cfg)
    raw = Path(path).read_text(encoding="utf-8-sig")
    meta, body = loaders.parse_frontmatter(raw)
    chunks = chunker.split_markdown(body, cfg.chunk["size"], cfg.chunk["overlap"])
    if not chunks:
        return 0
    vectors = embedder.embed([c["text"] for c in chunks])
    store.upsert_chunks(chunks, vectors, str(Path(path).resolve()),
                        loaders.file_hash(raw), loaders.tags_of(meta), "", Path(path).stat().st_mtime)
    return len(chunks)
