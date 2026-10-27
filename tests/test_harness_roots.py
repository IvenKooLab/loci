"""Each harness root is scanned independently.

A harness may declare several roots — Claude is `~/.claude/memories` plus a
single `~/.claude/CLAUDE.md`. The preset used to fall back to a recursive scan
of *the first root* whenever the harness as a whole had produced no files,
which pulled deep subdirectory content into a preset defined as top-level only
(`type = "codex"` means `*.md`, not `**/*.md`).
"""
from __future__ import annotations

from pathlib import Path

from loci.harness import Harness, _root, _root_prefix, memory_files


def test_codex_preset_stays_top_level(tmp_path):
    memories = tmp_path / ".claude" / "memories"
    deep = memories / "sub"
    deep.mkdir(parents=True)
    (deep / "deep.md").write_text("# deep\n", encoding="utf-8")
    top = tmp_path / ".claude" / "CLAUDE.md"
    top.write_text("# top\n", encoding="utf-8")

    h = Harness("claude", "codex", "🧠", [memories, top])
    names = [p.name for p in memory_files(h)]
    assert "CLAUDE.md" in names
    assert "deep.md" not in names, "empty first root fell back recursively"


def test_generic_preset_is_still_recursive(tmp_path):
    root = tmp_path / "dsh"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "deep.md").write_text("x", encoding="utf-8")
    h = Harness("dsh", "generic", "🐳", [root])
    assert [p.name for p in memory_files(h)] == ["deep.md"]


def test_second_root_still_contributes_when_the_first_is_empty(tmp_path):
    empty = tmp_path / "memories"
    empty.mkdir()
    single = tmp_path / "CLAUDE.md"
    single.write_text("# c\n", encoding="utf-8")
    h = Harness("claude", "codex", "🧠", [empty, single])
    assert [p.name for p in memory_files(h)] == ["CLAUDE.md"]


def test_a_non_markdown_file_root_is_ignored(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("x", encoding="utf-8")
    assert memory_files(Harness("x", "codex", "🗂️", [txt])) == []


def test_glob_root_needs_no_code_change(tmp_path):
    vault = tmp_path / "vault"
    (vault / "projects").mkdir(parents=True)
    (vault / "projects" / "one.md").write_text("x", encoding="utf-8")
    (vault / "top.md").write_text("x", encoding="utf-8")
    (vault / "skip.txt").write_text("x", encoding="utf-8")

    h = Harness("real", "generic", "🗂️", [_root(str(vault / "**" / "*.md"))])
    assert sorted(p.name for p in memory_files(h)) == ["one.md", "top.md"]


def test_glob_root_is_not_resolved_into_a_literal(tmp_path):
    pattern = str(tmp_path / "**" / "*.md")
    assert "*" in str(_root(pattern))
    assert "*" not in str(_root(str(tmp_path / "plain")))


def test_glob_root_prefix_for_chunk_attribution(tmp_path):
    pattern = str(tmp_path / "vault" / "**" / "*.md")
    assert _root_prefix(Path(pattern)) == str(tmp_path / "vault")
    plain = tmp_path / "vault"
    assert _root_prefix(plain) == str(plain)


def test_env_var_in_a_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCI_TEST_HOME", str(tmp_path))
    h = Harness("dsh", "generic", "🐳", [_root("$LOCI_TEST_HOME")])
    assert h.roots[0] == tmp_path.resolve()
