"""Lifecycle scan and retrieval-quality drift (additive; no behaviour change)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from conftest import make_cfg, write_corpus
from loci import governance, quality


# ------------------------------------------------------------- governance
def test_superseded_note_is_reported_as_still_live(tmp_path):
    sources = write_corpus(tmp_path, {
        "policy-v3.md": "---\nsuperseded_by: policy-v4\n---\n\n# 报销\n\n上限 500",
        "policy-v4.md": "---\nsupersedes: policy-v3\n---\n\n# 报销\n\n上限 800",
    })
    cfg = make_cfg(tmp_path, sources)
    findings = governance.scan(cfg, cited={})
    live = findings["superseded_live"]
    assert [row["file"] for row in live] == ["policy-v3.md"]
    assert live[0]["target_exists"] is True


def test_dangling_supersede_link_is_reported(tmp_path):
    sources = write_corpus(tmp_path, {
        "a.md": "---\nsupersedes: ghost-note\n---\n\n# A\n\nbody",
    })
    cfg = make_cfg(tmp_path, sources)
    assert governance.scan(cfg, cited={})["dangling"][0]["references"] == "ghost-note"


def test_duplicate_truth_needs_same_title_and_different_body(tmp_path):
    sources = write_corpus(tmp_path, {
        "a.md": "# 差旅报销\n\n上限 500 元",
        "b.md": "# 差旅报销\n\n上限 800 元",
        "c.md": "# 年假\n\n10 天",
    })
    cfg = make_cfg(tmp_path, sources)
    dupes = governance.scan(cfg, cited={})["duplicate_truth"]
    assert len(dupes) == 1
    assert set(dupes[0]["files"]) == {"a.md", "b.md"}


def test_identical_titles_with_identical_bodies_are_not_duplicates(tmp_path):
    sources = write_corpus(tmp_path, {
        "a.md": "# 停车\n\n200 元",
        "b.md": "# 停车\n\n200 元",
    })
    cfg = make_cfg(tmp_path, sources)
    assert governance.scan(cfg, cited={})["duplicate_truth"] == []


def test_stale_requires_both_age_and_zero_citations(tmp_path):
    sources = write_corpus(tmp_path, {"old.md": "# Old\n\nnobody reads me"})
    cfg = make_cfg(tmp_path, sources)
    old = time.time() - 400 * 86400
    path = Path(sources[0]["path"]) / "old.md"
    os.utime(path, (old, old))

    fresh_cited = {str(path.resolve()): {"count": 3}}
    assert governance.scan(cfg, cited=fresh_cited)["stale"] == []

    uncited = governance.scan(cfg, cited={})
    assert [row["file"] for row in uncited["stale"]] == ["old.md"]


def test_scan_never_modifies_the_corpus(tmp_path):
    sources = write_corpus(tmp_path, {
        "policy-v3.md": "---\nsuperseded_by: policy-v4\n---\n\n# 报销\n\n上限 500",
        "policy-v4.md": "# 报销\n\n上限 800",
    })
    cfg = make_cfg(tmp_path, sources)
    before = {p.name: p.read_bytes() for p in Path(sources[0]["path"]).iterdir()}
    governance.scan(cfg, cited={})
    after = {p.name: p.read_bytes() for p in Path(sources[0]["path"]).iterdir()}
    assert before == after


def test_report_is_readable_and_says_nothing_changed(tmp_path):
    sources = write_corpus(tmp_path, {
        "policy-v3.md": "---\nsuperseded_by: policy-v4\n---\n\n# 报销\n\n上限 500",
        "policy-v4.md": "# 报销\n\n上限 800",
    })
    cfg = make_cfg(tmp_path, sources)
    text = governance.report(governance.scan(cfg, cited={}))
    assert "SUPERSEDED BUT STILL INDEXED" in text
    assert "Nothing was changed" in text


def test_clean_corpus_says_so_without_claiming_truth(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\n\nbody"})
    cfg = make_cfg(tmp_path, sources)
    text = governance.report(governance.scan(cfg, cited={}))
    assert "no lifecycle findings" in text
    assert "not that it is true" in text


# ---------------------------------------------------------------- quality
def _write_queries(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_snapshot_measures_zero_hits_and_feedback(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\n\nbody"})
    cfg = make_cfg(tmp_path, sources)
    qlog = tmp_path / "queries.jsonl"
    cfg.http["query_log"] = str(qlog)
    _write_queries(qlog, [
        {"hits": 3, "ms": 10, "query": "a"},
        {"hits": 0, "ms": 12, "query": "b"},
        {"hits": 0, "ms": 8, "query": "c"},
        {"hits": 2, "ms": 9, "query": "d"},
    ])
    store_dir = Path(cfg.store["path"])
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "feedback.jsonl").write_text(
        json.dumps({"chunk_id": "x", "verdict": "bad"}) + "\n"
        + json.dumps({"chunk_id": "y", "verdict": "good"}) + "\n", encoding="utf-8")

    snap = quality.snapshot(cfg)
    assert snap["queries"] == 4
    assert snap["zero_hit_rate"] == 0.5
    assert snap["avg_hits"] == 1.25
    assert snap["bad_rate"] == 0.5


def test_no_query_log_is_reported_honestly(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\n\nbody"})
    cfg = make_cfg(tmp_path, sources)
    text = quality.report(quality.compare(cfg))
    assert "no query log yet" in text


def test_drift_flags_a_zero_hit_spike(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\n\nbody"})
    cfg = make_cfg(tmp_path, sources)
    base = {"zero_hit_rate": 0.0, "bad_rate": 0.0, "avg_hits": 3.0}
    cur = {"zero_hit_rate": 0.35, "bad_rate": 0.0, "avg_hits": 3.0,
           "feedback_total": 0}
    kinds = {a["kind"] for a in quality.drift(cur, base)}
    assert "zero_hit_spike" in kinds


def test_stale_truth_is_called_out_when_retrieval_still_hits(tmp_path):
    base = {"zero_hit_rate": 0.0, "bad_rate": 0.02, "avg_hits": 4.0}
    cur = {"zero_hit_rate": 0.0, "bad_rate": 0.4, "avg_hits": 4.0,
           "feedback_total": 50}
    kinds = {a["kind"] for a in quality.drift(cur, base)}
    assert "stale_truth" in kinds


def test_pin_then_compare_has_no_alerts(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\n\nbody"})
    cfg = make_cfg(tmp_path, sources)
    qlog = tmp_path / "queries.jsonl"
    cfg.http["query_log"] = str(qlog)
    _write_queries(qlog, [{"hits": 3, "ms": 10, "query": f"q{i}"} for i in range(30)])
    quality.pin(cfg)
    assert quality.compare(cfg)["alerts"] == []


def test_no_baseline_means_no_false_alarms(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\n\nbody"})
    cfg = make_cfg(tmp_path, sources)
    qlog = tmp_path / "queries.jsonl"
    cfg.http["query_log"] = str(qlog)
    _write_queries(qlog, [{"hits": 0, "ms": 10, "query": f"q{i}"} for i in range(30)])
    assert quality.compare(cfg)["alerts"] == []


def test_query_log_path_is_anchored_at_loci_home(tmp_path, monkeypatch):
    """A relative query_log must follow LOCI_HOME, not the process cwd."""
    from loci import config
    (tmp_path / "config.toml").write_text('[http]\nquery_log = "./queries.jsonl"\n',
                                          encoding="utf-8")
    monkeypatch.setenv("LOCI_HOME", str(tmp_path))
    cfg = config.load()
    assert cfg.http["query_log"] == str(tmp_path / "queries.jsonl")
    # and an absolute path must be left alone (an absolute Windows path has a
    # drive letter — on POSIX "/tmp/..." is already absolute, on Windows it is
    # not, and anchoring it is exactly what the feature promises)
    import sys as _sys
    absolute = ("C:/somewhere/queries.jsonl" if _sys.platform == "win32"
                else "/tmp/somewhere/queries.jsonl")
    (tmp_path / "config.toml").write_text(
        f'[http]\nquery_log = "{absolute}"\n', encoding="utf-8")
    assert config.load().http["query_log"] == absolute
