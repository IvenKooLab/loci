import pytest

from conftest import build_index, make_cfg, write_corpus
from second_brain import chunker


def test_per_source_chunk_size_override(tmp_path):
    """A [[sources]] entry's chunk_size/overlap beats the global [chunk] block."""
    long_text = "# Docs\n" + ("word " * 400)          # ~2000 chars
    small_text = "# Chat\n" + ("word " * 400)          # same, other directory
    big = tmp_path / "docs"
    small = tmp_path / "chat"
    big.mkdir()
    small.mkdir()
    (big / "big.md").write_text(long_text, encoding="utf-8")
    (small / "small.md").write_text(small_text, encoding="utf-8")

    cfg = make_cfg(tmp_path, [{"path": str(big)},           # global default 800
                              {"path": str(small),
                               "chunk_size": 2000,           # one big chunk
                               "chunk_overlap": 0}])
    _, store, _ = build_index(cfg)
    per_source = store.per_source()
    big_chunks = [v for k, v in per_source.items() if k.endswith("big.md")][0]
    small_chunks = [v for k, v in per_source.items() if k.endswith("small.md")][0]
    assert big_chunks > 1          # 2000 chars at size 800 → windowed
    assert small_chunks == 1       # fits whole at size 2000


def test_scan_sources_attaches_overrides(tmp_path):
    from second_brain import loaders
    (tmp_path / "n").mkdir()
    (tmp_path / "n" / "a.md").write_text("hello", encoding="utf-8")
    docs = loaders.scan_sources([{"path": str(tmp_path / "n"),
                                  "chunk_size": 400, "chunk_overlap": 40}])
    assert docs[0]["chunk_size"] == 400
    assert docs[0]["chunk_overlap"] == 40


def test_scan_sources_without_override_is_none(tmp_path):
    from second_brain import loaders
    (tmp_path / "n").mkdir()
    (tmp_path / "n" / "a.md").write_text("hello", encoding="utf-8")
    docs = loaders.scan_sources([{"path": str(tmp_path / "n")}])
    assert docs[0]["chunk_size"] is None  # None = use global default


def test_chunker_honors_custom_size():
    text = "# T\n" + ("word " * 600)
    one = chunker.split_markdown(text, size=4000, overlap=0)
    many = chunker.split_markdown(text, size=400, overlap=50)
    assert len(one) == 1
    assert len(many) > 1
