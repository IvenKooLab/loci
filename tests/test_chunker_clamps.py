"""split_markdown is called directly by per-source overrides, the demo and
harness digests — all bypassing config.load's clamps. overlap >= size used to
mean a step of <1 char and near-identical chunks indexed over and over."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci.chunker import split_markdown


def test_overlap_ge_size_clamps_to_half():
    text = "word " * 2000                        # 10k chars
    chunks = split_markdown(text, 100, 100)
    assert len(chunks) < 300, len(chunks)       # ~200, not ~10000


def test_garbage_params_fall_back(tmp_path):
    assert split_markdown("hello", "not-an-int", None)   # no raise
    assert split_markdown("hello", None, "junk")         # no raise


def test_sane_params_unchanged():
    text = "# T\n\n" + "word " * 400
    a = split_markdown(text, 800, 100)
    b = split_markdown(text, 800, 100)
    assert a == b                               # deterministic, untouched
