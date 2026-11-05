"""Citation ledger and memory health: adoption made observable.

File-based (JSONL ledgers), so these run without ChromaDB.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from loci import citations


class FakeCfg:
    def __init__(self, root: Path):
        self.store = {"path": str(root / "chroma_db")}
        self.memories = {"path": str(root / "memories")}
        self.state = {"path": str(root / "state")}


def _make_note(cfg, name: str, body: str = "note body", age_days: float = 0.0) -> Path:
    d = Path(cfg.memories["path"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    stamp = time.time() - age_days * 86400
    import os
    os.utime(p, (stamp, stamp))
    return p


def test_search_citations_are_ledgered_per_source(tmp_path):
    cfg = FakeCfg(tmp_path)
    note = _make_note(cfg, "20260101-000000-alpha.md")
    citations.record_citations(cfg, [str(note)], "how do we deploy?", via="search")
    path = Path(cfg.store["path"]) / "citations.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["source"] == str(note)
    assert rows[0]["via"] == "search"


def test_duplicate_sources_in_one_query_collapse(tmp_path):
    cfg = FakeCfg(tmp_path)
    note = _make_note(cfg, "20260101-000000-beta.md")
    citations.record_citations(cfg, [str(note), str(note)], "q")
    rows = [json.loads(l) for l in
            (Path(cfg.store["path"]) / "citations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1                       # one query, one line — not per hit


def test_record_never_raises_on_unwritable_path(tmp_path):
    class BrokenCfg(FakeCfg):
        pass
    cfg = BrokenCfg(tmp_path / "nowhere")       # parent dir does not exist
    # must be a no-op, not an exception into the caller's search result
    citations.record_citations(cfg, ["/x.md"], "q")


def test_health_counts_citations_and_flags_stale_uncited(tmp_path):
    cfg = FakeCfg(tmp_path)
    hot = _make_note(cfg, "20260101-000000-hot.md")
    _make_note(cfg, "20260101-000001-cold.md", age_days=45)   # old, never cited
    citations.record_citations(cfg, [str(hot)], "hot query")

    rows = citations.health(cfg)
    by_file = {r["file"]: r for r in rows}
    assert by_file["20260101-000000-hot.md"]["citations"] == 1
    assert by_file["20260101-000001-cold.md"]["flags"] == ["never-cited"]
    assert by_file["20260101-000000-hot.md"]["flags"] == []


def test_health_marks_corrected_notes(tmp_path):
    cfg = FakeCfg(tmp_path)
    note = _make_note(cfg, "20260101-000002-wrong.md")
    fb = Path(cfg.store["path"]) / "feedback.jsonl"
    fb.parent.mkdir(parents=True, exist_ok=True)
    # feedback is per chunk id: "<source>::<index>"
    fb.write_text(json.dumps({"chunk_id": f"{note}::0", "verdict": "bad"}) + "\n",
                  encoding="utf-8")
    rows = citations.health(cfg)
    assert rows[0]["corrections"] == 1
    assert "corrected" in rows[0]["flags"]


def test_health_sorts_most_cited_first(tmp_path):
    cfg = FakeCfg(tmp_path)
    a = _make_note(cfg, "20260101-000003-a.md")
    b = _make_note(cfg, "20260101-000004-b.md")
    citations.record_citations(cfg, [str(b)], "q1")
    citations.record_citations(cfg, [str(b)], "q2")
    citations.record_citations(cfg, [str(a)], "q3")
    rows = citations.health(cfg)
    assert rows[0]["file"].endswith("b.md")


def test_torn_ledger_line_does_not_kill_the_report(tmp_path):
    cfg = FakeCfg(tmp_path)
    note = _make_note(cfg, "20260101-000005-x.md")
    ledger = Path(cfg.store["path"]) / "citations.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{torn line\n" +
                      json.dumps({"ts": 1, "source": str(note), "query": "q"}) + "\n",
                      encoding="utf-8")
    rows = citations.health(cfg)
    assert rows[0]["citations"] == 1            # good line survived the torn one
