"""The overlap clamp said "avoid 1-char steps" while clamping to size-1 —
which IS a 1-char step: overlap=99/size=100 over an 80k-char corpus produced
~80k near-identical chunks (index size and embedding bill explode)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from loci import config


@pytest.mark.parametrize("overlap,want", [(100, 50), (150, 50), (99, 50), (51, 50), (50, 50), (30, 30)])
def test_overlap_clamps_to_half_size(tmp_path, overlap, want):
    (tmp_path / "config.toml").write_text(
        f"[chunk]\nsize = 100\noverlap = {overlap}\n", encoding="utf-8")
    cfg = config.load(str(tmp_path / "config.toml"))
    assert cfg.chunk["overlap"] == want
