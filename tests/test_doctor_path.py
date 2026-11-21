"""`loci doctor` checked Path("config.toml") — the process cwd — while
config.load() reads LOCI_HOME/config.toml when that env var is set: a launchd
or cron deployment (the exact audience of LOCI_HOME) got "config.toml missing"
from a healthy instance, right above green endpoint checks."""
import sys
from pathlib import Path

import pytest

from loci import config


def test_doctor_uses_resolved_config_path(tmp_path, monkeypatch, capsys):
    home = tmp_path / "instance"
    home.mkdir()
    (home / "config.toml").write_text(
        "[store]\npath = './chroma'\n", encoding="utf-8")
    monkeypatch.setenv("LOCI_HOME", str(home))
    monkeypatch.chdir(tmp_path)                # cwd deliberately differs

    cfg = config.load()
    assert cfg.config_path == str(home / "config.toml")

    from loci.cli import cmd_doctor
    cmd_doctor(cfg)                       # exit code depends on keys/endpoints;
    out = capsys.readouterr().out          # this test pins the config line only
    assert f"{home / 'config.toml'} found" in out
    assert "config.toml missing" not in out
