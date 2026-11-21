"""A blank query from the CLI must not reach the embedding endpoint.

`loci search ""` used to call embed([""]) — providers answer 400 and the
user saw a raw traceback (the MCP layer already rejected blank queries;
the CLI entry did not)."""
from __future__ import annotations

import pytest


class Cfg:
    chunk = {"size": 800, "overlap": 100}
    embed = {"base_url": "http://x", "api_key": "k", "model": "m"}
    store = {"path": "unused"}


@pytest.mark.parametrize("cmd", ["search", "ask"])
def test_blank_query_is_rejected_before_any_api_call(cmd, monkeypatch):
    from loci import cli

    # any attempt to reach the network means the guard failed
    monkeypatch.setattr(cli, "build",
                        lambda cfg: (_ for _ in ()).throw(
                            AssertionError("guard must exit before build")))
    with pytest.raises(SystemExit, match="empty"):
        if cmd == "search":
            cli.cmd_search(Cfg(), "   ")
        else:
            cli.cmd_ask(Cfg(), "")


@pytest.mark.parametrize("cmd", ["search", "ask"])
def test_nonblank_query_passes_the_guard(cmd, monkeypatch):
    from loci import cli

    calls = []
    monkeypatch.setattr(cli, "build", lambda cfg: calls.append(1) or (None, None))
    monkeypatch.setattr(cli, "make_retriever", lambda cfg, e, s: (
        (_ for _ in ()).throw(StopIteration)))  # not reached further
    with pytest.raises(StopIteration):
        if cmd == "search":
            cli.cmd_search(Cfg(), "T8 加速")
        else:
            cli.cmd_ask(Cfg(), "T8 加速")
    assert calls == [1]              # build happened: guard let a real query through
