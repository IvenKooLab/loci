"""GET /memories on a fresh instance.

The memories directory is created by the first `loci remember` (or by an
ingest that has something to store). Until then it does not exist, and
_list_memories called iterdir() on it: FileNotFoundError, a 500, and an
error dialog on the console's Memories tab of a brand-new install.
"""
from __future__ import annotations

from types import SimpleNamespace

from loci.http_api import Audit, _make_handler


def _handler(tmp_path, mem_dir):
    monkey = SimpleNamespace(memories={"path": str(mem_dir)},
                             http={"icons": str(tmp_path), "local_admin": False})
    cls = _make_handler(SimpleNamespace(), monkey,
                        [{"token": "t", "role": "admin", "label": "t"}], Audit())
    return cls.__new__(cls)


def test_no_memories_directory_yields_an_empty_list(tmp_path):
    handler = _handler(tmp_path, tmp_path / "not-created-yet")
    assert handler._list_memories() == []


def test_an_empty_directory_yields_an_empty_list(tmp_path):
    mem = tmp_path / "mem"
    mem.mkdir()
    assert _handler(tmp_path, mem)._list_memories() == []


def test_once_a_note_exists_it_is_listed(tmp_path):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "note.md").write_text("---\ntitle: T\n---\nbody\n", encoding="utf-8")
    rows = _handler(tmp_path, mem)._list_memories()
    assert [r["name"] for r in rows] == ["note.md"] and rows[0]["title"] == "T"
