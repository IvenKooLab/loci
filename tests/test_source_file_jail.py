"""/source-file jails by the harness roots. A root may be a glob —
`paths = ["~/.claude/**/*.md"]`, "so a new tool needs no code change" — and
the jail resolved that pattern literally, which matches no real directory:
discovery found the files, search indexed them, and opening any of them in
the console (the evidence pane, the harness drilldown) answered 404.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loci import harness
from loci.http_api import Audit, _make_handler


def _handler(tmp_path, monkeypatch, pattern):
    roots = [harness._root(pattern)]
    monkeypatch.setattr("loci.harness.load_harnesses",
                        lambda cfg: [harness.Harness("h", "generic", "x", roots)])
    cfg = SimpleNamespace(memories={"path": str(tmp_path / "mem")},
                          http={"icons": str(tmp_path), "local_admin": False})
    cls = _make_handler(SimpleNamespace(), cfg,
                        [{"token": "t", "role": "admin", "label": "t"}], Audit())
    return cls.__new__(cls), roots[0]


def test_a_file_reached_through_a_glob_root_can_be_opened(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    (notes / "sub").mkdir(parents=True)
    target = notes / "sub" / "x.md"
    target.write_text("hello", encoding="utf-8")
    handler, root = _handler(tmp_path, monkeypatch, str(notes / "**" / "*.md"))

    assert target in harness.memory_files(harness.Harness("h", "generic", "x", [root]))  # discovery works
    assert handler._safe_source(str(target)) == target.resolve()        # …and so does opening it


def test_the_glob_jail_still_holds(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "in.md").write_text("in", encoding="utf-8")
    outside = tmp_path / "notes-archive"
    outside.mkdir()
    (outside / "out.md").write_text("out", encoding="utf-8")
    (tmp_path / "top.md").write_text("top", encoding="utf-8")
    handler, _ = _handler(tmp_path, monkeypatch, str(notes / "**" / "*.md"))

    assert handler._safe_source(str(notes / "in.md")) is not None
    assert handler._safe_source(str(outside / "out.md")) is None        # sibling prefix is not inside
    assert handler._safe_source(str(tmp_path / "top.md")) is None


def test_a_glob_with_a_wildcard_in_the_middle_jails_by_its_fixed_part(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    (notes / "a" / "sub").mkdir(parents=True)
    (notes / "a" / "sub" / "x.md").write_text("x", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "y.md").write_text("y", encoding="utf-8")
    handler, _ = _handler(tmp_path, monkeypatch, str(notes / "*" / "sub" / "*.md"))

    assert handler._safe_source(str(notes / "a" / "sub" / "x.md")) is not None
    assert handler._safe_source(str(elsewhere / "y.md")) is None


def test_a_plain_root_is_unaffected(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "in.md").write_text("in", encoding="utf-8")
    handler, _ = _handler(tmp_path, monkeypatch, str(notes))
    assert handler._safe_source(str(notes / "in.md")) is not None
    assert handler._safe_source(str(tmp_path / "outside.md")) is None
