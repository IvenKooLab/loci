"""Memory notes are found by folded suffix, everywhere they are listed.

The index (scan_sources) and the memory API treat NOTE.MD as a note — on
macOS and Windows a uppercase extension is a perfectly ordinary file. But
brain_forget's lookup and the memory-health report listed notes with
`glob("*.md")`, and pathlib's glob is case-sensitive on macOS and Linux:
there such a note was indexed and readable, yet could not be forgotten and
never appeared in the health report.

(On Windows pathlib's glob already matches case-insensitively, so this
reproduces on macOS/Linux — and on the Linux CI.)
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loci import citations, memories


def _notes(tmp_path):
    d = tmp_path / "mem"
    d.mkdir()
    (d / "lower.md").write_text("the deployment token rotates monthly", encoding="utf-8")
    (d / "UPPER.MD").write_text("the DEPLOYMENT window is Sunday", encoding="utf-8")
    (d / "Mixed.Md").write_text("deploy via blue-green", encoding="utf-8")
    (d / "notes.txt").write_text("not a memory", encoding="utf-8")
    (d / "._lower.md").write_bytes(b"\x00\x05\x16\x07")        # AppleDouble sidecar
    (d / "~$lower.md").write_bytes(b"owner lock")               # Office owner-lock file
    (d / "sub").mkdir()
    (d / "sub" / "nested.md").write_text("nested", encoding="utf-8")
    return d


def test_memory_notes_lists_every_markdown_spelling_and_nothing_else(tmp_path):
    names = [p.name for p in memories.memory_notes(_notes(tmp_path))]
    assert sorted(names) == ["Mixed.Md", "UPPER.MD", "lower.md"]


def test_memory_notes_on_a_missing_directory_is_empty(tmp_path):
    assert memories.memory_notes(tmp_path / "nope") == []


def test_find_memories_sees_uppercase_extensions(tmp_path):
    d = _notes(tmp_path)
    found = sorted(p.name for p in memories.find_memories(str(d), "deployment"))
    assert found == ["UPPER.MD", "lower.md"]


def test_memory_health_reports_uppercase_extensions(tmp_path, monkeypatch):
    d = _notes(tmp_path)
    cfg = SimpleNamespace(memories={"path": str(d)}, store={"path": str(tmp_path / "store")})
    monkeypatch.setattr(citations, "_ledger_path", lambda cfg: tmp_path / "none.jsonl")
    rows = {r["file"] for r in citations.health(cfg)}
    assert rows == {"lower.md", "UPPER.MD", "Mixed.Md"}


def test_forget_reaches_an_uppercase_note(tmp_path):
    d = _notes(tmp_path)
    moved = memories.forget_memory(str(d), "window")
    assert [Path(m).name for m in moved] == ["UPPER.MD"]
    assert not (d / "UPPER.MD").exists() and (d / ".trash" / "UPPER.MD").is_file()
