"""Editing a memory through the console (POST /memory with `name`).

Two faults in one branch. `tmp.rename(p)` raises FileExistsError on Windows
whenever the target exists — every console edit was a 500 there. And the
editor loads and saves the WHOLE file, frontmatter included, while the server
prepended the OLD frontmatter to what it received: one edit duplicated the
frontmatter into the body and silently dropped edits to tags/title.
"""
from __future__ import annotations

from types import SimpleNamespace

from loci import loaders
from loci.http_api import Audit, _make_handler

ORIGINAL = "---\ntitle: T\ntags: [memory]\n---\n# T\n\nold body\n"


def _handler(tmp_path, monkeypatch, mem):
    monkeypatch.setattr("loci.harness.load_harnesses", lambda _: [])
    cfg = SimpleNamespace(memories={"path": str(mem)},
                          http={"icons": str(tmp_path), "local_admin": False},
                          store={"path": str(tmp_path / "chroma")})
    cls = _make_handler(SimpleNamespace(), cfg,
                        [{"token": "t", "role": "admin", "label": "t"}], Audit())

    class H(cls):
        def _json(self, code, data):
            self.code, self.data = code, data

    return H


def _edit(H, body):
    h = H.__new__(H)
    h.entry = {"label": "t", "role": "admin"}
    h._memory_write(body)
    return h.code


def test_body_only_update_replaces_the_note_in_place(tmp_path, monkeypatch):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "note.md").write_text(ORIGINAL, encoding="utf-8")
    H = _handler(tmp_path, monkeypatch, mem)

    assert _edit(H, {"name": "note.md", "text": "# T\n\nnew body"}) == 200
    saved = (mem / "note.md").read_text(encoding="utf-8")
    assert saved == "---\ntitle: T\ntags: [memory]\n---\n# T\n\nnew body\n"
    assert list(mem.glob("*.tmp")) == []           # no staging file left behind


def test_whole_file_save_keeps_exactly_one_frontmatter_block(tmp_path, monkeypatch):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "note.md").write_text(ORIGINAL, encoding="utf-8")
    H = _handler(tmp_path, monkeypatch, mem)
    whole = "---\ntitle: T2\ntags: [memory, edited]\n---\n# T2\n\nbody\n"

    assert _edit(H, {"name": "note.md", "text": whole}) == 200
    saved = (mem / "note.md").read_text(encoding="utf-8")
    assert saved == whole                          # not old frontmatter + whole file
    meta, body = loaders.parse_frontmatter(saved)
    assert meta["title"] == "T2" and meta["tags"] == ["memory", "edited"]
    assert not body.lstrip().startswith("---")
