"""`loci forget` — the command the governance report keeps recommending.

The report said "drop it from the index (loci forget) and keep the file for
history" in three places; the CLI had no such subcommand (argparse: invalid
choice). It retires memories the way brain_forget does: soft-delete into
.trash, chunks out of the index.

And the advice has to be true for the note it is attached to: `loci forget`
only reaches the memories directory, so for a note that lives in a source
directory the report now says what actually retires it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import FakeEmbedder, make_cfg
from loci import cli, governance
from loci.store import Store


def _cfg(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, [])
    mem = tmp_path / "mem"
    mem.mkdir()
    cfg.memories["path"] = str(mem)
    monkeypatch.setattr(cli, "build", lambda cfg: (FakeEmbedder(), Store(cfg.store["path"])))
    return cfg, mem


def test_forget_retires_matching_memories_and_drops_their_chunks(tmp_path, monkeypatch, capsys):
    cfg, mem = _cfg(tmp_path, monkeypatch)
    (mem / "token.md").write_text("the deployment token rotates monthly", encoding="utf-8")
    (mem / "lunch.md").write_text("an unrelated note about lunch", encoding="utf-8")
    store = Store(cfg.store["path"])
    for name in ("token.md", "lunch.md"):
        store.upsert_chunks([{"text": name, "section": ""}], [[0.1] * 128],
                            str((mem / name).resolve()), "h")

    cli.cmd_forget(cfg, "deployment")

    assert {Path(s).name for s in store.list_sources()} == {"lunch.md"}
    assert not (mem / "token.md").exists()
    assert (mem / ".trash" / "token.md").is_file()                 # recoverable by hand
    assert "token.md" in capsys.readouterr().out


def test_forget_with_no_match_says_so_and_changes_nothing(tmp_path, monkeypatch, capsys):
    cfg, mem = _cfg(tmp_path, monkeypatch)
    (mem / "lunch.md").write_text("about lunch", encoding="utf-8")
    cli.cmd_forget(cfg, "deployment")
    assert "no memory matching" in capsys.readouterr().out
    assert (mem / "lunch.md").exists()


@pytest.mark.parametrize("query", ["", "   "])
def test_forget_needs_a_query(tmp_path, monkeypatch, query):
    cfg, mem = _cfg(tmp_path, monkeypatch)
    (mem / "lunch.md").write_text("about lunch", encoding="utf-8")
    with pytest.raises(SystemExit, match="query"):
        cli.cmd_forget(cfg, query)
    assert (mem / "lunch.md").exists()                              # a blank query retires nothing


def test_the_subcommand_exists(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["loci", "forget", "--help"])
    with pytest.raises(SystemExit) as stop:
        cli.main()                                                  # argparse exits after --help
    assert stop.value.code == 0
    assert "query" in capsys.readouterr().out


# ---------- the advice attached to a finding is true for that note ----------
class _GovCfg:
    def __init__(self, root, memories):
        self.sources = [{"path": str(root)}]
        self.memories = {"path": str(memories)}
        self.governance = {"stale_days": 180}


def _superseded(folder, name="old.md", target="new.md"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(f"---\nsuperseded_by: {target}\n---\nold rule\n", encoding="utf-8")
    (folder / target).write_text("# New\n\nnew rule\n", encoding="utf-8")


def test_a_superseded_memory_is_retired_with_forget(tmp_path):
    mem = tmp_path / "memories"
    _superseded(mem)
    (tmp_path / "findings.jsonl").write_text("", encoding="utf-8")   # the sources entry needs a folder
    finding = governance.scan(_GovCfg(tmp_path, mem))["superseded_live"]
    finding = [f for f in finding if Path(f["path"]).parent == mem]
    assert "loci forget old" in finding[0]["action"]


def test_a_superseded_source_note_gets_advice_that_can_retire_it(tmp_path):
    src = tmp_path / "docs"
    _superseded(src)
    finding = governance.scan(_GovCfg(src, tmp_path / "memories"))["superseded_live"]
    assert finding and "loci forget" not in finding[0]["action"]        # forget cannot reach a source note
    assert "loci ingest" in finding[0]["action"]
