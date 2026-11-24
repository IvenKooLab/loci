"""Two ordinary argument slips answered with a traceback.

`loci wiki` with no topic sent None into the retriever ("AttributeError:
'NoneType' object has no attribute 'replace'"), and `loci state save task k
42` raised ValueError from the store ("state data must be a JSON object or
array") with a stack. Both are usage questions; usage gets one line.
"""
from __future__ import annotations

import pytest

from conftest import make_cfg
from loci import cli, state


class WikiCfg:
    embed = {"base_url": "x", "api_key": "k", "model": "m"}
    store = {"path": "unused"}


@pytest.mark.parametrize("topic", [None, "", "   "])
def test_wiki_without_a_topic_prints_how_to_give_one(monkeypatch, topic):
    # any attempt to open the index means the guard did not run first
    monkeypatch.setattr(cli, "build", lambda cfg: (_ for _ in ()).throw(
        AssertionError("must exit before build")))
    with pytest.raises(SystemExit) as stop:
        cli.cmd_wiki(WikiCfg(), topic)
    assert "topic" in str(stop.value) and "--suggest" in str(stop.value)


def test_state_save_with_a_scalar_explains_what_it_takes(tmp_path):
    cfg = make_cfg(tmp_path, [])
    cfg.state["path"] = str(tmp_path / "state")
    for data in ('"just a string"', "42"):
        with pytest.raises(SystemExit, match="object or array") as stop:
            cli.cmd_state(cfg, "save", "task", "k", data)
        assert "Traceback" not in str(stop.value)


def test_a_real_record_still_saves(tmp_path):
    cfg = make_cfg(tmp_path, [])
    cfg.state["path"] = str(tmp_path / "state")
    cli.cmd_state(cfg, "save", "task", "k", '{"ok": true}')
    assert state.get(cfg, "task", "k") == {"ok": True}
