"""BM25 index cache.

Building the BM25 index is O(corpus) and used to happen on *every* query:
`_fuse` pulled every chunk out of the store and rebuilt from scratch — 144 ms
at 5k chunks, 291 ms at 10k. For a `serve-http` or MCP process answering many
queries over the same unchanged index, that is pure waste.

Two things can make a cached index wrong, so the cache key covers both:

- *writes*: `Store` bumps a process-wide per-path version counter inside
  `upsert_chunks` / `delete_file` / `reset`, so any writer — CLI ingest,
  `remember`, the console, the watcher — invalidates without the cache
  knowing any call site.
- *out-of-process writers*: a second process holding the same Chroma directory
  has its own counter, so the key also carries a digest of the chunk ids. That
  is exact — any added, removed or replaced chunk changes it — and costs a few
  milliseconds against the hundreds that rebuilding BM25 costs.

`all_chunks()` still runs on every query (the store read is what makes the
digest trustworthy); what the cache removes is the O(corpus) tokenize-and-count
pass on top of it.

Nothing here changes ranking: a cache hit is the same BM25 over the same texts.
"""
from __future__ import annotations

import zlib
from pathlib import Path

from loci.bm25 import BM25
from loci.tokenizers import get_tokenizer

# resolved store path -> mutation counter, shared by every Store in this process
_VERSIONS: dict[str, int] = {}


def store_key(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def bump(path: str | Path) -> None:
    """Called by Store after a write so caches keyed on this path go stale."""
    key = store_key(path)
    _VERSIONS[key] = _VERSIONS.get(key, 0) + 1


def version(path: str | Path) -> int:
    return _VERSIONS.get(store_key(path), 0)


class BM25Cache:
    """Holds the last BM25 built for one store + one tokenizer."""

    def __init__(self):
        self._bm25: BM25 | None = None
        self._key: tuple | None = None

    @staticmethod
    def fingerprint(ids: list[str]) -> tuple:
        """(count, digest) — count alone would miss a same-size swap, and a
        digest of the ids is the cheapest exact-ish proxy for "same chunks"."""
        if not ids:
            return (0, 0)
        return (len(ids), zlib.crc32("\x00".join(ids).encode("utf-8")))

    def get(self, store_path: str, ids: list[str], docs: list[str],
            tokenizer: str) -> BM25:
        key = (store_key(store_path), version(store_path),
               self.fingerprint(ids), tokenizer)
        if self._bm25 is not None and self._key == key:
            return self._bm25
        self._bm25 = BM25(dict(zip(ids, docs)),
                          tokenizer=get_tokenizer(tokenizer))
        self._key = key
        return self._bm25

    def clear(self) -> None:
        self._bm25 = None
        self._key = None
