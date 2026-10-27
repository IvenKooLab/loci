"""The BM25 index cache must never change a result, only skip the rebuild.

Building BM25 is O(corpus) and used to run on every query. The cache is keyed
on (store, in-process write counter, content fingerprint, tokenizer), so these
tests are about *invalidation*: a stale index would silently re-rank results,
which is worse than the milliseconds it saves.
"""
from __future__ import annotations

from loci import bm25_cache
from loci.bm25 import BM25
from loci.bm25_cache import BM25Cache
from loci.tokenizers import get_tokenizer

IDS = ["a.md::0", "a.md::1", "b.md::0"]
DOCS = ["alpha beta gamma", "检索 与 向量", "delta alpha epsilon"]
PATH = "/tmp/loci-cache-test/db"


def test_reuses_while_the_corpus_is_unchanged():
    cache = BM25Cache()
    first = cache.get(PATH, IDS, DOCS, "default")
    second = cache.get(PATH, IDS, DOCS, "default")
    assert first is second


def test_respects_the_tokenizer():
    cache = BM25Cache()
    assert cache.get(PATH, IDS, DOCS, "default") is not \
        cache.get(PATH, IDS, DOCS, "cjk_bigram")


def test_a_write_in_this_process_invalidates():
    cache = BM25Cache()
    before = cache.get(PATH, IDS, DOCS, "default")
    bm25_cache.bump(PATH)
    assert cache.get(PATH, IDS, DOCS, "default") is not before


def test_a_different_corpus_invalidates():
    cache = BM25Cache()
    before = cache.get(PATH, IDS, DOCS, "default")
    assert cache.get(PATH, IDS[:2], DOCS[:2], "default") is not before


def test_a_same_size_swap_changes_the_fingerprint():
    swapped = ["a.md::0", "a.md::9", "b.md::0"]      # same count, new tail
    assert BM25Cache.fingerprint(IDS) != BM25Cache.fingerprint(swapped)


def test_cached_scores_equal_a_fresh_build():
    cached = BM25Cache().get(PATH, IDS, DOCS, "cjk_bigram")
    fresh = BM25(dict(zip(IDS, DOCS)),
                 tokenizer=get_tokenizer("cjk_bigram"))
    assert cached.score("检索") == fresh.score("检索")


def test_stores_with_the_same_path_share_the_counter():
    # a second Store on the same directory must see the first one's writes
    cache = BM25Cache()
    before = cache.get(PATH, IDS, DOCS, "default")
    bm25_cache.bump(PATH + "/")                      # trailing slash, same dir
    assert cache.get(PATH, IDS, DOCS, "default") is not before
