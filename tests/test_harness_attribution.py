"""Harness stats attribute indexed chunks to a harness by path prefix.

The prefix test was a plain startswith, so a root `…/mini` claimed every
chunk of the sibling `…/minimax-h3-turing/docs`: a harness with three
indexed notes could report 202. "Under a root" is the root itself or
something below it — a directory boundary, not a string prefix.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from loci import harness

TOP = Path(r"E:\data") if sys.platform == "win32" else Path("/data")


class FakeStore:
    def __init__(self, per_source):
        self.per = per_source

    def per_source(self):
        return self.per


def _chunks(tmp_path, root, per_source):
    tool = harness.Harness("mini", "generic", "x", [Path(root)])
    cfg = SimpleNamespace(memories={"path": str(tmp_path / "no-memories")})
    return harness.stats(cfg, FakeStore(per_source), [tool])[0]["chunks"]


PER_SOURCE = {
    str(TOP / "mini" / "notes" / "a.md"): 3,
    str(TOP / "minimax-h3-turing" / "docs" / "b.md"): 199,
    str(TOP / "elsewhere" / "c.md"): 7,
}


def test_a_sibling_with_the_same_string_prefix_is_not_claimed(tmp_path):
    assert _chunks(tmp_path, TOP / "mini", PER_SOURCE) == 3        # was 202


def test_the_root_itself_and_everything_below_it_are_counted(tmp_path):
    per = {str(TOP / "notes" / "a.md"): 2, str(TOP / "notes" / "deep" / "b" / "c.md"): 5}
    assert _chunks(tmp_path, TOP / "notes", per) == 7


def test_a_single_file_root_counts_that_file(tmp_path):
    per = {str(TOP / "CLAUDE.md"): 4, str(TOP / "CLAUDE-extra.md"): 9}
    assert _chunks(tmp_path, TOP / "CLAUDE.md", per) == 4


@pytest.mark.skipif(sys.platform != "win32", reason="drive-letter case folding is Windows semantics")
def test_a_root_typed_in_another_case_still_counts_on_windows(tmp_path):
    per = {"E:\\data\\Mini\\Notes\\a.md": 3}          # as the index recorded it
    assert _chunks(tmp_path, "e:\\DATA\\mini", per) == 3          # as someone typed it in config
