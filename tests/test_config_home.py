"""LOCI_HOME: anchor a whole instance (config + store + memories + wiki) at
one directory regardless of cwd — for launchd/cron/systemd deployments that
don't honor a wrapper script's `cd`. Born from the ECS deployment of the
wechat → git-vault → dual-node RAG pipeline."""
import os

import pytest

from loci import config


@pytest.fixture(autouse=True)
def _no_loci_home(monkeypatch):
    monkeypatch.delenv("LOCI_HOME", raising=False)


def test_loci_home_anchors_config_and_runtime_paths(tmp_path, monkeypatch):
    home = tmp_path / "instance"
    home.mkdir()
    (home / "config.toml").write_text(
        '[store]\npath = "./chroma_db"\n'
        '[[sources]]\npath = "./notes"\n', encoding="utf-8")
    (home / "notes").mkdir()

    monkeypatch.setenv("LOCI_HOME", str(home))
    monkeypatch.chdir(tmp_path)                # cwd is NOT the instance dir
    cfg = config.load()

    assert cfg.store["path"] == str(home / "chroma_db")
    assert cfg.sources[0]["path"] == str(home / "notes")


def test_absolute_paths_left_untouched(tmp_path, monkeypatch):
    home = tmp_path / "instance"
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    raw_path = str(elsewhere / "db")
    (home / "config.toml").write_text(
        "[store]\npath = \"{}\"\n".format(raw_path.replace("\\", "\\\\")), encoding="utf-8")

    monkeypatch.setenv("LOCI_HOME", str(home))
    cfg = config.load()
    assert cfg.store["path"] == raw_path


def test_explicit_path_wins_over_loci_home(tmp_path, monkeypatch):
    home = tmp_path / "instance"
    home.mkdir()
    other = tmp_path / "other.toml"
    other.write_text("[chunk]\nsize = 500\n", encoding="utf-8")

    monkeypatch.setenv("LOCI_HOME", str(home))
    cfg = config.load(str(other))
    assert cfg.chunk["size"] == 500


def test_without_loci_home_behaviour_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[store]\npath = "./chroma_db"\n', encoding="utf-8")
    cfg = config.load()
    assert cfg.store["path"] == "./chroma_db"  # still cwd-relative, not rewritten
