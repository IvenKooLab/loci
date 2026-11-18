"""Windows drive-letter case must not zero out a live source.

The same directory spelled E:/x, e:/x or with backslashes is one
directory to Windows; a config typed in any of those spellings used to
make chunks_for report 0 chunks for an indexed, healthy source.
"""
from __future__ import annotations

import sys

import pytest

from loci.mcp_server import Brain


@pytest.mark.skipif(sys.platform != "win32", reason="drive-case folding is Windows semantics")
def test_chunks_for_folds_drive_letter_case(monkeypatch):
    b = Brain.__new__(Brain)          # no config/network in __init__

    class Store:
        @staticmethod
        def per_source():
            return {r"E:\work\docs\a.md": 2, r"E:\work\docs\sub\b.md": 3}

    b._store = Store()
    monkeypatch.setattr(b, "_guard", lambda: False)
    assert b.chunks_for(r"E:\work\docs") == 5        # exact
    assert b.chunks_for("e:/WORK/docs") == 5         # case + separators
    assert b.chunks_for(r"E:\work") == 5             # parent directory
    assert b.chunks_for(r"E:\work\docs\a.md") == 2   # a file, exact
