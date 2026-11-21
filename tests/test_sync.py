"""cmd_sync swallowed every git returncode: a dead remote, a rejected push
or a pull conflict still printed "push done" — the user believed their
memories were synced when they weren't. Failures now print the git tail
and the command exits non-zero; "nothing to commit" stays a success."""
from __future__ import annotations

import subprocess

import pytest

from loci.cli import cmd_sync
from conftest import make_cfg


class FakeRun:
    """Scriptable _sp.run double, keyed by the first git argument."""
    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, args, **k):
        self.calls.append(tuple(args))
        r = self.results.get(args[1] if len(args) > 1 else args[0])
        if r is None:
            r = (0, "", "")
        code, out, err = r
        return subprocess.CompletedProcess(args, code, out, err)


def _cfg(tmp_path):
    cfg = make_cfg(tmp_path, [])
    cfg.sync = {"remote": "git@example:user/repo"}
    return cfg


def test_sync_reports_push_failure(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    fake = FakeRun({"commit": (0, "", ""),
                    "push": (1, "", "ERROR: permission denied")})
    monkeypatch.setattr("subprocess.run", fake)
    with pytest.raises(SystemExit):
        cmd_sync(cfg, "push")
    out = capsys.readouterr().out
    assert "permission denied" in out
    assert "pushed" not in out
    assert "2 error(s)" in out   # memories + wiki both fail


def test_sync_nothing_to_commit_is_not_an_error(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    fake = FakeRun({"commit": (1, "nothing to commit, working tree clean", ""),
                    "push": (0, "", "")})       # commit says clean; no push
    monkeypatch.setattr("subprocess.run", fake)
    cmd_sync(cfg, "push")                       # must not raise
    out = capsys.readouterr().out
    assert "nothing to commit" in out and "error(s)" not in out


def test_sync_pull_failure_reports(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    fake = FakeRun({"pull": (1, "", "CONFLICT (content): Merge conflict in a.md")})
    monkeypatch.setattr("subprocess.run", fake)
    with pytest.raises(SystemExit):
        cmd_sync(cfg, "pull")
    assert "CONFLICT" in capsys.readouterr().out


def test_sync_success_still_prints(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    fake = FakeRun({"commit": (0, "", ""), "push": (0, "", "")})
    monkeypatch.setattr("subprocess.run", fake)
    cmd_sync(cfg, "push")
    out = capsys.readouterr().out
    assert "memories: pushed" in out and "wiki: pushed" in out
