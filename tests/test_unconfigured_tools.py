"""Every index-backed tool answers setup guidance on an unconfigured instance
— except brain_governance and brain_quality, which read self._cfg directly
(None there) and died with AttributeError. And the quality snapshot trusted
its own inputs: a window that is not an int, a hand-edited log line that is
not an object, or a non-numeric field each raised out of the report.
"""
from __future__ import annotations

import pytest

import loci.mcp_server as mcp
from loci import config, governance, quality


@pytest.fixture
def unconfigured(monkeypatch):
    # a Config with no keys and no sources fails validate(): the "fresh install" state
    monkeypatch.setattr(mcp.config, "load", lambda path="config.toml": config.Config())
    return mcp.Brain()


@pytest.mark.parametrize("call", [
    lambda brain: brain.governance(),
    lambda brain: brain.governance(30),
    lambda brain: brain.quality("report"),
    lambda brain: brain.quality("pin"),
    lambda brain: brain.quality("pin", "abc"),
])
def test_unconfigured_instance_gets_setup_guidance_not_a_crash(unconfigured, call):
    reply = call(unconfigured)
    assert "not configured" in reply
    assert "AttributeError" not in reply


class _LogCfg:
    def __init__(self, log, store):
        self.http = {"query_log": str(log)}
        self.store = {"path": str(store)}


def test_snapshot_tolerates_a_hand_edited_log_and_a_garbage_window(tmp_path):
    log = tmp_path / "q.jsonl"
    log.write_text(
        '{"hits": 1, "ms": 5, "query": "a"}\n'
        '[1, 2]\n'                                   # not an object
        '{"hits": 0, "ms": "slow", "query": "b"}\n'  # ms is not a number
        '{"hits": "many", "ms": 7, "query": "c"}\n',
        encoding="utf-8")
    cfg = _LogCfg(log, tmp_path / "chroma")

    snap = quality.snapshot(cfg, "abc")             # window is not an int
    assert snap["queries"] == 3
    assert snap["window"] == quality.DEFAULT_WINDOW
    assert snap["zero_hit_rate"] == pytest.approx(2 / 3, abs=1e-3)   # 0 and "many" are both no hits
    assert snap["avg_ms"] == pytest.approx(4.0)     # "slow" counts as 0, not a crash

    assert quality.snapshot(cfg, 0)["window"] == quality.DEFAULT_WINDOW
    assert quality.snapshot(cfg, -3)["window"] == quality.DEFAULT_WINDOW
    assert quality.snapshot(cfg, 2)["queries"] == 2


def test_governance_tolerates_a_stale_days_that_is_not_an_int(tmp_path):
    class Cfg:
        sources = [{"path": str(tmp_path)}]
        governance = {"stale_days": "soon"}

    findings = governance.scan(Cfg())               # config value is not an int
    assert findings["scanned"] == 0
    assert governance.scan(Cfg(), stale_days="30")["scanned"] == 0
    assert governance.scan(Cfg(), stale_days="soon")["scanned"] == 0
