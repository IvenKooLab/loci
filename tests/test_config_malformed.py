"""One malformed [[sources]] entry (path as an int/list, missing path) used to
crash every loci command at config load; harness `paths = "~/notes"` (a bare
string) was iterated per CHARACTER, registering "/" among the roots."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from loci import config, harness


def test_malformed_source_entries_are_skipped_with_a_pointer(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[[sources]]\npath = "~/real"\n'
        '[[sources]]\npath = 123\n'
        '[[sources]]\nchunk_size = 5\n'
        '[[sources]]\npath = ["a"]\n', encoding="utf-8")
    (tmp_path / "real").mkdir()
    cfg = config.load(str(tmp_path / "config.toml"))
    assert [s["path"] for s in cfg.sources] == ["~/real"]
    out = capsys.readouterr().err
    assert out.count("skipped") == 3


def test_sources_not_a_table_array(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("[[sources]]\n", encoding="utf-8")
    # a bare [[sources]] with no keys still parses as a table array — use a
    # plain key to force the non-list shape
    (tmp_path / "config.toml").write_text("sources = \"oops\"\n", encoding="utf-8")
    cfg = config.load(str(tmp_path / "config.toml"))
    assert cfg.sources == []
    assert "not a table array" in capsys.readouterr().err


def test_harness_string_paths_is_one_root(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[[harness]]\nname = "x"\ntype = "generic"\npaths = "~/notes"\n',
        encoding="utf-8")
    cfg = config.load(str(tmp_path / "config.toml"))
    hs = {h.name: h for h in harness.load_harnesses(cfg)}
    # registry-discovered harnesses may coexist on a real machine — only our
    # config entry's roots matter here
    assert hs["x"].roots == [(Path.home() / "notes").resolve()]
    assert all("/" != str(r) for h in hs.values() for r in h.roots)
