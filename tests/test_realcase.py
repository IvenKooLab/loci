"""macOS APFS is case-preserving but case-insensitive: /a/Notes and /a/notes
are one directory, while os.path.normcase is a no-op on POSIX. Chunk
attribution keyed by path strings therefore reported 0 for a differently-cased
spelling of a live source (the drive-letter Windows twin is in
test_chunks_for_case)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loci.fsutil import realcase
from loci.mcp_server import Brain


def test_realcase_folds_to_disk_spelling(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    realcase.cache_clear()
    (tmp_path / "Notes" / "Sub").mkdir(parents=True)
    (tmp_path / "Notes" / "Sub" / "a.md").write_text("x", encoding="utf-8")

    assert realcase(str(tmp_path / "notes")) == str(tmp_path / "Notes")
    assert realcase(str(tmp_path / "NOTES/sub")) == str(tmp_path / "Notes" / "Sub")
    # exact spelling passes through unchanged
    assert realcase(str(tmp_path / "Notes")) == str(tmp_path / "Notes")
    realcase.cache_clear()


def test_realcase_missing_ancestor_is_inert(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    realcase.cache_clear()
    ghost = tmp_path / "nope" / "Whatever"
    assert realcase(str(ghost)) == str(ghost)
    realcase.cache_clear()


def test_realcase_identity_off_darwin(tmp_path):
    if sys.platform == "darwin":
        pytest.skip("identity branch needs a non-darwin platform value")
    assert realcase(str(tmp_path)) == str(tmp_path)


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="needs a real case-insensitive volume")
def test_chunks_for_folds_case_on_apfs(tmp_path):
    b = Brain.__new__(Brain)
    real = tmp_path / "Docs"
    real.mkdir()
    f = real / "a.md"
    f.write_text("hello", encoding="utf-8")

    class Store:
        @staticmethod
        def per_source():
            return {str(f): 2}

    b._store = Store()
    b._guard = lambda: False
    assert b.chunks_for(str(tmp_path / "Docs")) == 2       # exact
    assert b.chunks_for(str(tmp_path / "docs")) == 2       # APFS: same dir
    assert b.chunks_for(str(tmp_path / "DOCS")) == 2
