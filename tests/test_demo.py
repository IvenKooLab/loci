"""`loci demo` must work on a machine with no config.toml, no API key and no
network — that is the entire point of shipping it."""
from __future__ import annotations

import sys

import pytest

from loci import cli, demo


def test_corpus_ships_with_the_package():
    files = sorted(p.name for p in demo.CORPUS.rglob("*") if p.is_file())
    assert "decisions.md" in files
    assert "battery-budget.md" in files
    assert len(files) >= 5


def test_ensure_corpus_copies_then_reuses_and_respects_reset(tmp_path):
    dest = tmp_path / "notes"

    files, copied = demo.ensure_corpus(dest)
    assert copied and files >= 5
    edited = dest / "projects" / "aurora" / "README.md"
    edited.write_text("# my own edits\n", encoding="utf-8")

    files, copied = demo.ensure_corpus(dest)          # second run: no clobber
    assert not copied and files >= 5
    assert edited.read_text(encoding="utf-8") == "# my own edits\n"

    _, copied = demo.ensure_corpus(dest, reset=True)  # --reset restores it
    assert copied
    assert "aurora" in edited.read_text(encoding="utf-8").lower()


def test_search_returns_cited_sections(tmp_path):
    demo.ensure_corpus(tmp_path / "n")
    index = demo.DemoIndex(tmp_path / "n")

    hits = index.search("why did the humidity sensor replace the BME280")
    assert hits, "the sample corpus should answer its own example query"
    top = hits[0]
    assert top["source"] == "projects/aurora/decisions.md"
    assert "SHT45" in top["section"]
    assert top["rel"] == pytest.approx(1.0)


def test_tag_and_path_filters_narrow_the_corpus(tmp_path):
    demo.ensure_corpus(tmp_path / "n")
    index = demo.DemoIndex(tmp_path / "n")

    tagged = index.search("reconnect storms", tag="meetings")
    assert tagged and all("meetings" in h["source"] for h in tagged)

    scoped = index.search("power budget", path_contains="notes/")
    assert scoped and all(h["source"].startswith("notes/") for h in scoped)

    assert index.search("power budget", tag="no-such-tag") == []


def test_empty_query_does_not_crash(tmp_path):
    demo.ensure_corpus(tmp_path / "n")
    assert demo.DemoIndex(tmp_path / "n").search("   ") == []


def test_cli_demo_runs_without_any_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)                      # no config.toml here
    monkeypatch.setattr(sys, "argv", ["loci", "demo", "--no-input"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "projects/aurora/decisions.md" in out
    assert "keyword only" in out
    assert (tmp_path / demo.DEFAULT_DIR).is_dir()


def test_cli_demo_respects_dir_and_missing_config(tmp_path, monkeypatch, capsys):
    target = tmp_path / "elsewhere"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["loci", "demo", "--no-input", "--dir", str(target), "-k", "1"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    assert (target / "projects" / "aurora" / "README.md").exists()
    out = capsys.readouterr().out
    assert out.count("(bm25") == 3        # three examples, one hit each with -k 1


def test_no_config_warning_leaks_into_demo_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["loci", "demo", "--no-input"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "config.toml not found" not in capsys.readouterr().err
