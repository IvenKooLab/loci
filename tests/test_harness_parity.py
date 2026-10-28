"""The native build ports harness detection; the two must agree.

These are the cases where a port silently drifts: preset shapes (flat vs
recursive), the per-root fallback, and registry-vs-config precedence. They run
against the Python implementation so a Rust change that disagrees shows up as a
failing test here rather than as a user noticing missing notes.
"""
from __future__ import annotations

from pathlib import Path

from loci import config, harness as hm


def _write(path: Path, body: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_codex_preset_is_flat(tmp_path):
    root = tmp_path / "codex"
    _write(root / "MEMORY.md")
    _write(root / "note.md")
    _write(root / "sub" / "deep.md")
    h = hm.Harness("codex", "codex", "🐙", [root])
    assert sorted(p.name for p in hm.memory_files(h)) == ["MEMORY.md", "note.md"]


def test_zcode_falls_back_to_recursive(tmp_path):
    root = tmp_path / "zcode"
    _write(root / "a" / "b" / "c.md")
    h = hm.Harness("z", "zcode", "⚡", [root])
    assert [p.name for p in hm.memory_files(h)] == ["c.md"]


def test_generic_is_recursive(tmp_path):
    root = tmp_path / "g"
    _write(root / "x" / "y" / "z.md")
    h = hm.Harness("g", "generic", "🦜", [root])
    assert [p.name for p in hm.memory_files(h)] == ["z.md"]


def test_fallback_is_per_root(tmp_path):
    memories = tmp_path / "claude" / "memories"
    memories.mkdir(parents=True)
    _write(memories / "sub" / "deep.md")
    top = tmp_path / "claude" / "CLAUDE.md"
    _write(top)
    h = hm.Harness("claude", "codex", "🧠", [memories, top])
    names = [p.name for p in hm.memory_files(h)]
    assert "CLAUDE.md" in names
    assert "deep.md" not in names


def test_glob_root_needs_no_code_change(tmp_path):
    _write(tmp_path / "projects" / "one.md")
    _write(tmp_path / "top.md")
    _write(tmp_path / "skip.txt")
    h = hm.Harness("real", "generic", "🗂️", [hm._root(str(tmp_path / "**" / "*.md"))])
    assert sorted(p.name for p in hm.memory_files(h)) == ["one.md", "top.md"]


def test_root_prefix_strips_the_wildcard(tmp_path):
    assert hm._root_prefix(Path("/v/**/*.md")) == "/v"
    assert hm._root_prefix(tmp_path) == str(tmp_path)


def test_config_entry_overrides_the_registry(tmp_path):
    cfg = config.Config()
    cfg.harnesses = [{"name": "zcode", "type": "generic",
                      "paths": [str(tmp_path)], "display": "My ZCode"}]
    found = {h.name: h for h in hm.load_harnesses(cfg)}
    assert found["zcode"].display == "My ZCode"
    assert found["zcode"].type == "generic"


def test_a_new_harness_can_be_added_by_config_alone(tmp_path):
    cfg = config.Config()
    cfg.harnesses = [{"name": "my-tool", "type": "generic", "paths": [str(tmp_path)]}]
    found = {h.name: h for h in hm.load_harnesses(cfg)}
    assert "my-tool" in found
    assert found["my-tool"].icon == "🗂️"


def test_fingerprint_is_order_stable(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    _write(a, "a")
    _write(b, "b")
    assert hm.fingerprint([a, b]) == hm.fingerprint([b, a])
