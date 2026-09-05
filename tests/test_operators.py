import os
import time

import pytest

from conftest import build_index, make_cfg, write_corpus


def make(tmp_path, files, top_k=5):
    sources = write_corpus(tmp_path, files)
    cfg = make_cfg(tmp_path, sources)
    cfg.top_k["search"] = top_k
    _, _, retriever = build_index(cfg)
    return retriever


def age_file(path, years_ago=2.0):
    old = time.time() - years_ago * 365 * 86400
    os.utime(path, (old, old))


def test_path_filter_narrows_to_matching_paths(tmp_path):
    files = {
        "sub/a.md": "# A\nunique alpha content here",
        "b.md": "# B\nunique alpha content here too",
    }
    r = make(tmp_path, files)
    hits = r.search("unique alpha content", path_contains="sub")
    assert hits and all("sub" in h["source"] for h in hits)
    all_hits = r.search("unique alpha content")
    assert len(all_hits) > len(hits)


def test_since_filter_excludes_old_files(tmp_path):
    r = make(tmp_path, {
        "old.md": "# Old\nretrievable retro content",
        "new.md": "# New\nretrievable retro content",
    })
    # make one file look two years old, then force a re-index pass
    age_file(tmp_path / "notes" / "old.md")
    from loci import loaders, chunker
    from conftest import FakeEmbedder
    from loci.store import Store
    store = Store(r.store.path)
    embedder = FakeEmbedder()
    for doc in loaders.scan_sources([{"path": str(tmp_path / "notes")}]):
        chunks = chunker.split_markdown(doc["content"], 800, 100)
        vecs = embedder.embed([c["text"] for c in chunks])
        store.upsert_chunks(chunks, vecs, doc["path"], doc["hash"],
                            doc["tags"], doc["links"], doc["mtime"])
    cutoff = time.time() - 86400  # yesterday
    hits = r.search("retrievable retro content", since=cutoff)
    assert hits and all(h["mtime"] >= cutoff for h in hits)
    assert all(h["source"].endswith("new.md") for h in hits)


def test_exact_phrase_filters_non_matching_chunks(tmp_path):
    r = make(tmp_path, {
        "a.md": "# A\nthe quick brown fox jumps",
        "b.md": "# B\nthe slow brown turtle walks",
    })
    hits = r.search("quick brown", exact="fox jumps")
    assert len(hits) == 1 and hits[0]["source"].endswith("a.md")


def test_filters_combine_with_tag(tmp_path):
    from conftest import build_index
    files = {
        "x.md": "---\ntags: [rag]\n---\n# X\nhybrid fusion vector keywords",
        "y.md": "# Y\nhybrid fusion vector keywords",
    }
    r = make(tmp_path, files)
    hits = r.search("hybrid fusion vector", tag="rag", exact="vector")
    assert len(hits) == 1 and hits[0]["tags"] == "rag"


def test_parse_since_accepts_both_formats():
    from loci.cli import parse_since
    mid_month = parse_since("2026-08-15")
    month_start = parse_since("2026-08")
    assert mid_month > month_start > 0  # YYYY-MM resolves to the 1st, 00:00
    with pytest.raises(ValueError, match="bad --since"):
        parse_since("not-a-date")
