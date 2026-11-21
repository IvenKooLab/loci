"""The feedback loop was born broken: `loci ask` never wrote the
.last_ask.json that `loci feedback` reads, so `good|bad` always answered
"no recent ask to rate". Brain.ask now persists the chunk ids atomically,
and the rater tolerates a torn file instead of crashing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from loci.cli import cmd_feedback
from loci.mcp_server import Brain
from conftest import FakeEmbedder, make_cfg, write_corpus


def _brain(tmp_path, monkeypatch, hits):
    b = Brain.__new__(Brain)
    b._config_error = None
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, {"a.md": "# A\nsensor data"}))
    b._cfg = cfg
    from loci.store import Store
    b._store = Store(cfg.store["path"])

    class Retriever:
        @staticmethod
        def search(query, **k):
            return hits
    b._retriever = Retriever()
    monkeypatch.setattr("loci.retriever.answer",
                        lambda llm, q, h, history=None: "answer text")
    return b, cfg


def test_ask_persists_last_ask_and_feedback_rates_it(tmp_path, monkeypatch, capsys):
    hits = [{"id": "a.md::0", "source": "x", "section": "", "text": "t",
             "tags": "", "distance": 0.1}]
    b, cfg = _brain(tmp_path, monkeypatch, hits)

    b.ask("what about the sensor?")
    last = Path(cfg.store["path"]) / ".last_ask.json"
    assert last.exists()
    data = json.loads(last.read_text(encoding="utf-8"))
    assert data["chunk_ids"] == ["a.md::0"] and data["query"] == "what about the sensor?"

    cmd_feedback(cfg, "good")                    # previously: "no recent ask"
    fb = Path(cfg.store["path"]) / "feedback.jsonl"
    rows = [json.loads(l) for l in fb.read_text(encoding="utf-8").splitlines() if l]
    assert rows and rows[0]["chunk_id"] == "a.md::0" and rows[0]["verdict"] == "good"


def test_feedback_tolerates_a_torn_file(tmp_path, capsys):
    cfg = make_cfg(tmp_path, [])
    Path(cfg.store["path"]).mkdir(parents=True, exist_ok=True)
    (Path(cfg.store["path"]) / ".last_ask.json").write_text(
        '{"chunk_ids": ["x"', encoding="utf-8")     # torn write
    cmd_feedback(cfg, "bad")
    assert "corrupted" in capsys.readouterr().out


def test_no_hits_ask_does_not_clobber_last_ask(tmp_path, monkeypatch):
    hits = [{"id": "a.md::0", "source": "x", "section": "", "text": "t",
             "tags": "", "distance": 0.1}]
    b, cfg = _brain(tmp_path, monkeypatch, hits)
    b.ask("good query")
    b._retriever.search = staticmethod(lambda q, **k: [])   # zero-hit ask
    b.ask("useless query")
    data = json.loads((Path(cfg.store["path"]) / ".last_ask.json")
                      .read_text(encoding="utf-8"))
    assert data["chunk_ids"] == ["a.md::0"]        # still the rateable answer


def test_cli_ask_also_persists_last_ask(tmp_path, monkeypatch, capsys):
    """`loci ask` bypasses Brain.ask (retriever.answer direct) — it used to
    never write .last_ask.json either, so the CLI feedback loop stayed dead
    even after the MCP/HTTP fix."""
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, {"a.md": "# A\nsensor data"}))
    from loci.store import Store
    store = Store(cfg.store["path"])
    hits = [{"id": "a.md::0", "source": str(tmp_path / "notes" / "a.md"),
             "section": "", "text": "sensor data", "tags": "",
             "mtime": 0.0, "distance": None}]
    monkeypatch.setattr("loci.cli.build",
                        lambda c: (FakeEmbedder(), store))
    monkeypatch.setattr("loci.cli.make_retriever",
                        lambda c, e, s: type("R", (), {"search": staticmethod(
                            lambda q, **k: hits)})())
    monkeypatch.setattr("loci.retriever.answer",
                        lambda llm, q, h, history=None: "cli answer")
    # table_for hits the real filesystem — keep it empty to stay offline
    import loci.supersede as sup
    monkeypatch.setattr(sup, "table_for", lambda sources, mem="": {})

    from loci.cli import cmd_ask
    cmd_ask(cfg, "sensor question")
    last = Path(cfg.store["path"]) / ".last_ask.json"
    assert last.exists()
    data = json.loads(last.read_text(encoding="utf-8"))
    assert data["chunk_ids"] == ["a.md::0"]
