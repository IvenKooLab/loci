"""build_graph never dropped edges of files that vanished: a retired
decision's triples stayed in graph.json forever, steering answers about it
(governance/supersede got the same-family fixes earlier)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci import graph


def _cfg(tmp_path):
    class Cfg:
        store = {"path": str(tmp_path / "chroma")}
        memories = {"path": str(tmp_path / "memories")}
        wiki = {"path": str(tmp_path / "wiki")}
        llm = {"api_key": "test", "base_url": "x", "model": "m"}
    return Cfg()


def test_vanished_file_loses_its_edges(tmp_path, monkeypatch, capsys):
    mem = tmp_path / "memories"
    mem.mkdir()
    note = mem / "decision.md"
    note.write_text("---\ntitle: d\n---\nsome decision", encoding="utf-8")

    cfg = _cfg(tmp_path)
    # offline: skip extraction entirely, edges come from the pre-seeded graph
    monkeypatch.setattr(graph, "_extract_triples",
                        lambda llm_cfg, text: [["T8", "speeds_up", "drafts"]])
    r1 = graph.build_graph(cfg, dirs=[str(mem)])
    assert r1["edges"] == 1
    seed = json.loads((tmp_path / "chroma" / "graph.json").read_text())
    assert seed["edges"][0]["s"] == "T8"

    # the note is retired (deleted) — edges must go with it
    note.unlink()
    r2 = graph.build_graph(cfg, dirs=[str(mem)], force=True)  # no LLM: skipped
    assert r2["edges"] == 0
    final = json.loads((tmp_path / "chroma" / "graph.json").read_text())
    assert final["edges"] == []
    assert "decision.md" not in json.dumps(final["processed"])
    assert "dropped edges" in capsys.readouterr().out


def test_hidden_dirs_not_scanned(tmp_path):
    mem = tmp_path / "memories"
    (mem / ".trash").mkdir(parents=True)
    (mem / ".trash" / "gone.md").write_text("---\ntitle: g\n---\n", encoding="utf-8")
    cfg = _cfg(tmp_path)
    monkeypatch_rglob = None
    r = graph.build_graph(cfg, dirs=[str(mem)])
    assert r["files"] == 0                     # nothing outside hidden dirs
