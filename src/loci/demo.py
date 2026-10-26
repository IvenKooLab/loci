"""`loci demo` — a no-configuration tour of a small sample knowledge base.

The demo copies a fictional note collection next to the caller, chunks it with
the same splitter `loci ingest` uses, and answers queries with the same BM25
implementation that supplies the lexical half of hybrid search. Retrieval only:
no chat call, no embedding request, no `config.toml`, no network.

Vector and hybrid retrieval switch on once `[embed]` is configured. The demo
says so plainly instead of faking an embedding server, so what it shows is
exactly what it claims to show.
"""
from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path

from loci import chunker, loaders
from loci.bm25 import BM25

CORPUS = Path(__file__).resolve().parent / "demo_notes"
DEFAULT_DIR = "loci-demo-notes"

# same defaults as [chunk] in config.example.toml
CHUNK_SIZE, CHUNK_OVERLAP = 800, 100
K = 3

SAMPLE_QUERIES = [
    ("why did the humidity sensor replace the BME280?", None),
    ("how long can the station run on one charge?", None),
    ("what went wrong with wifi?", {"tag": "meetings"}),
]

HELP = """\
  /tag NAME     only notes carrying that frontmatter tag
  /in PATH      only notes whose path contains PATH
  /files        list the sample corpus
  /quit         leave the demo"""


def ensure_corpus(dest: Path, reset: bool = False) -> tuple[int, bool]:
    """Copy the bundled notes to `dest` unless they are already there.
    Returns (file count, copied) — an existing corpus is left alone so edits
    survive; `reset=True` restores the pristine copy."""
    if reset or not dest.exists() or not any(dest.rglob("*.md")):
        shutil.copytree(CORPUS, dest, dirs_exist_ok=True)
        copied = True
    else:
        copied = False
    return sum(1 for _ in dest.rglob("*.md")), copied


class DemoIndex:
    """In-memory chunk index over a directory, ranked by BM25 only."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()   # scan_sources resolves; match it so
                                           # citations stay relative on macOS
                                           # (/var -> /private/var symlink)
        self.chunks: dict[str, dict] = {}
        docs = loaders.scan_sources([{"path": str(self.root)}])
        for doc in docs:
            size, overlap = chunker.params_for(
                doc, {"size": CHUNK_SIZE, "overlap": CHUNK_OVERLAP})
            for part in chunker.split_markdown(doc["content"], size, overlap):
                cid = f"{len(self.chunks):04d}"
                self.chunks[cid] = {
                    "id": cid,
                    "text": part["text"],
                    "section": part["section"],
                    "source": self._rel(doc["path"]),
                    "tags": doc["tags"],
                }
        self.bm25 = BM25({cid: c["text"] for cid, c in self.chunks.items()})
        self.files = len(docs)

    def _rel(self, path: str) -> str:
        try:
            return Path(path).relative_to(self.root).as_posix()
        except ValueError:      # resolved through a symlink — keep the tail
            return Path(path).name

    def search(self, query: str, tag: str | None = None,
               path_contains: str | None = None, k: int = K) -> list[dict]:
        hits = [dict(self.chunks[cid], score=score)
                for cid, score in self.bm25.score(query)]
        if tag:
            want = tag.lower()
            hits = [h for h in hits
                    if want in [t.strip().lower()
                                for t in h["tags"].split(",") if t.strip()]]
        if path_contains:
            needle = path_contains.lower().replace("\\", "/")
            hits = [h for h in hits if needle in h["source"].lower()]
        if hits:
            top = hits[0]["score"] or 1.0
            for h in hits:
                h["rel"] = h["score"] / top
        return hits[:k]


_MD_NOISE = re.compile(r"\*\*|\*|`|^#{1,6}\s+|^[-*]\s+", re.M)


def _plain(text: str) -> str:
    """Markdown reduced to readable prose for the one-line preview: drop the
    heading line (the citation already shows it) and strip emphasis markers."""
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    text = _MD_NOISE.sub("", "\n".join(lines) or text)
    return " ".join(text.split())


def _cite(source: str, section: str) -> str:
    """`file > deepest heading` — the H1 crumb repeats the file title, so drop
    it and keep the part that actually locates the passage."""
    parts = [p for p in section.split(" > ") if p]
    if len(parts) > 1:
        parts = parts[1:]
    return f"{source} > {' > '.join(parts)}" if parts else source


def _print_hits(hits: list[dict]) -> None:
    if not hits:
        print("    (no matches — matching is literal, so try fewer"
              " or different words)")
        return
    for i, h in enumerate(hits, 1):
        print(f"  [{i}] {_cite(h['source'], h['section'])}   (bm25 {h['rel']:.2f})")
        print(f"      {_plain(h['text'])[:150]}…")


def _ask(index: DemoIndex, query: str, tag: str | None = None,
         path_contains: str | None = None, k: int = K) -> None:
    started = time.perf_counter()
    hits = index.search(query, tag=tag, path_contains=path_contains, k=k)
    ms = (time.perf_counter() - started) * 1000
    scope = ""
    if tag:
        scope += f"   tag={tag}"
    if path_contains:
        scope += f"   in={path_contains}"
    print(f"\n  {query}{scope}   [{ms:.1f} ms]")
    _print_hits(hits)


def _repl(index: DemoIndex, k: int = K) -> None:
    print("\nAsk your own question in plain words — or use a filter:")
    print(HELP)
    while True:
        try:
            line = input("\ndemo> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            return
        if line == "/files":
            for src in sorted({h["source"] for h in index.chunks.values()}):
                print(f"  {src}")
            continue
        if line.startswith(("/tag ", "/in ")):
            # `/tag meetings what went wrong` — filter and query on one line;
            # a bare `/tag meetings` prompts for the query instead
            cmd, _, rest = line.partition(" ")
            value, _, query = rest.strip().partition(" ")
            if not query.strip():
                query = input("query> ").strip() if sys.stdin.isatty() else ""
            if query.strip():
                kw = "tag" if cmd == "/tag" else "path_contains"
                _ask(index, query.strip(), k=k, **{kw: value.strip()})
            continue
        _ask(index, line, k=k)


def run_demo(directory: str | None = None, reset: bool = False,
             interactive: bool | None = None, k: int = K) -> int:
    dest = Path(directory).expanduser() if directory else Path.cwd() / DEFAULT_DIR
    dest = dest.resolve()
    files, copied = ensure_corpus(dest, reset=reset)

    index = DemoIndex(dest)
    print("loci demo — shared memory for your notes, in five minutes\n")
    print(f"  corpus    {dest}")
    print(f"            {files} files · {len(index.chunks)} chunks"
          f"{', just copied and safe to edit' if copied else ', reused as-is'}")
    print("  retrieval keyword only (BM25) — the same ranking hybrid search")
    print("            fuses with vector hits. No config, no key, no network.")
    print("            Add [embed] to config.toml to switch on vector + hybrid.\n")

    for i, (query, opts) in enumerate(SAMPLE_QUERIES, 1):
        label = f"-- example {i}/{len(SAMPLE_QUERIES)} "
        print(f"\n{label}{'-' * max(60 - len(label), 3)}")
        _ask(index, query, k=k, **(opts or {}))

    if interactive is None:
        interactive = sys.stdin.isatty()
    if interactive:
        _repl(index, k=k)

    print("\nNext steps")
    print("  loci ingest && loci search \"your question\"   index your own notes")
    print("  loci serve                                  mount as an MCP server")
    print("  loci doctor                                 check config and endpoints")
    print("  https://github.com/IvenKooLab/loci          issues, docs, ideas")
    return 0
