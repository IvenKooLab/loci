"""table_for's cache key was (roots, newest-mtime): an edit whose coarse clock
tick didn't move kept the stale table, and DELETING a superseded note never
lowered the newest mtime — the deleted note kept steering answers. The key is
now (mtime_ns, size) per file, over a pruned scan (no hidden dirs / sidecars)."""
from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci import supersede
from loci.supersede import table_for


def _cfg(tmp_path):
    class Cfg:
        sources = [{"path": str(tmp_path / "notes")}]
    return Cfg()


def test_deleted_superseded_note_leaves_the_table(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    old = notes / "old-decision.md"
    old.write_text("---\ntitle: old\n---\nold body", encoding="utf-8")
    new = notes / "new-decision.md"
    new.write_text(
        "---\ntitle: new\nsupersedes: old-decision\neffective: 2026-01-01\n---\nnew body",
        encoding="utf-8")

    cfg = _cfg(tmp_path)
    table = table_for(cfg.sources, "")
    assert table["old-decision"]["superseded_by"] == "new-decision"

    # the user retires the OLD note (forget moves it into .trash → outside roots)
    old.unlink()
    table2 = table_for(cfg.sources, "")
    # old-decision survives only as collect()'s inferred placeholder (path ""
    # — the walk needs it); the important part is the CACHE was rebuilt,
    # i.e. the file really left the scan
    assert table2["old-decision"]["path"] == ""
    assert table2["new-decision"]["supersedes"] == "old-decision"


def test_cache_invalidates_on_same_mtime_rewrite(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    note = notes / "note.md"
    note.write_text("---\ntitle: v1\nsuperseded_by: other\n---\nv1 body",
                    encoding="utf-8")

    cfg = _cfg(tmp_path)
    t1 = table_for(cfg.sources, "")
    assert t1["note"]["superseded_by"] == "other"

    import os
    st = note.stat()
    note.write_text("---\ntitle: v2\nsuperseded_by: other2\n---\nv2 body",
                    encoding="utf-8")
    os.utime(note, ns=(st.st_atime_ns, st.st_mtime_ns))   # force same clock tick

    t2 = table_for(cfg.sources, "")
    # same mtime, different size: the (mtime_ns, size) key must invalidate the
    # stale table (mtime alone used to keep serving the old superseded_by)
    assert t2["note"]["superseded_by"] == "other2"


def test_hidden_dirs_and_sidecars_excluded(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / ".trash" / "gone.md").parent.mkdir(parents=True)
    (notes / ".trash" / "gone.md").write_text(
        "---\ntitle: gone\nsuperseded_by: x\n---\n", encoding="utf-8")
    (notes / "._gone.md").write_bytes(b"\x00junk")
    (notes / "real.md").write_text("plain", encoding="utf-8")

    table = table_for(_cfg(tmp_path).sources, "")
    assert set(table) == set()                    # nothing machine-made in here
