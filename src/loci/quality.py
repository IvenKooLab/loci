"""Retrieval quality: notice the slide before a user complains.

A RAG service has no error rate in the usual sense — every request returns
200. The only early signals are shape-of-traffic ones:

    zero-hit queries rising        the corpus stopped covering the questions
    ratings turning bad            the answers were wrong, not just thin
    hit counts falling             an ACL or an ingest broke

This module reads the query log, the feedback log and the citation ledger that
loci already writes, reduces them to one snapshot per window, and compares that
snapshot against a pinned baseline. It is deliberately statistics-light: the
failure being watched for is a step change over weeks, not an anomaly to be
detected in milliseconds.

`loci quality` prints a snapshot; `--baseline` compares and exits non-zero on a
regression, so it can run in CI or cron.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

DEFAULT_WINDOW = 200
ZERO_HIT_ALERT = 0.10        # absolute rise that counts as a regression
BAD_RATE_ALERT = 0.08


def _query_log_path(cfg) -> Path | None:
    raw = (cfg.http or {}).get("query_log")
    return Path(str(raw)).expanduser() if raw else None


def _store_dir(cfg) -> Path:
    return Path(str((cfg.store or {}).get("path", "./chroma_db"))).expanduser()


def load_queries(cfg, window: int = DEFAULT_WINDOW) -> list[dict]:
    """Last `window` query-log lines; empty when logging was never enabled."""
    path = _query_log_path(cfg)
    if not path or not path.exists():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-window * 4:]:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows[-window:]


def load_feedback(cfg) -> list[dict]:
    path = _store_dir(cfg) / "feedback.jsonl"
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def snapshot(cfg, window: int = DEFAULT_WINDOW) -> dict:
    """One window of observable retrieval health."""
    queries = load_queries(cfg, window)
    feedback = load_feedback(cfg)
    n = len(queries)
    zero = sum(1 for q in queries if not q.get("hits"))
    hits = [q.get("hits", 0) for q in queries]
    ms = [q.get("ms", 0.0) for q in queries]
    bad = sum(1 for f in feedback if f.get("verdict") == "bad")
    good = sum(1 for f in feedback if f.get("verdict") == "good")

    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "queries": n,
        "zero_hit_rate": round(zero / n, 4) if n else 0.0,
        "avg_hits": round(sum(hits) / n, 2) if n else 0.0,
        "avg_ms": round(sum(ms) / n, 1) if n else 0.0,
        "p95_ms": round(statistics.quantiles(ms, n=20)[-1], 1) if len(ms) >= 20 else None,
        "feedback_total": len(feedback),
        "bad_rate": round(bad / (bad + good), 4) if (bad + good) else 0.0,
        "feedback_coverage": round((bad + good) / max(1, n), 4) if n else 0.0,
        "window": window,
    }


def drift(current: dict, baseline: dict) -> list[dict]:
    """Compare two snapshots; return alerts, worst first."""
    alerts: list[dict] = []
    if not baseline:
        return alerts
    dz = current.get("zero_hit_rate", 0.0) - baseline.get("zero_hit_rate", 0.0)
    if dz >= ZERO_HIT_ALERT:
        alerts.append({
            "kind": "zero_hit_spike", "severity": "warning",
            "message": f"zero-hit queries {baseline.get('zero_hit_rate', 0):.0%} -> "
                       f"{current.get('zero_hit_rate', 0):.0%}",
            "likely": "ingest lag, a moved/renamed source, or an over-tight filter",
        })
    db = current.get("bad_rate", 0.0) - baseline.get("bad_rate", 0.0)
    if db >= BAD_RATE_ALERT and current.get("feedback_total", 0) >= 10:
        alerts.append({
            "kind": "feedback_degradation", "severity": "critical",
            "message": f"bad-answer rate {baseline.get('bad_rate', 0):.0%} -> "
                       f"{current.get('bad_rate', 0):.0%}",
            "likely": "the corpus still holds superseded documents, or a source "
                      "stopped updating",
        })
    dh = current.get("avg_hits", 0.0) - baseline.get("avg_hits", 0.0)
    if dh <= -1.0:
        alerts.append({
            "kind": "fewer_hits", "severity": "warning",
            "message": f"average hits per query {baseline.get('avg_hits', 0):.1f} -> "
                       f"{current.get('avg_hits', 0):.1f}",
            "likely": "pruned sources, a broken loader, or an embedding mismatch",
        })
    # the signature of a corpus that drifted away from the truth
    if current.get("zero_hit_rate", 0.0) <= baseline.get("zero_hit_rate", 1.0) \
            and db >= BAD_RATE_ALERT:
        alerts.append({
            "kind": "stale_truth", "severity": "critical",
            "message": "retrieval still finds sources, but the answers got worse",
            "likely": "the index confidently returns documents that are no longer "
                      "true — run `loci governance` and retire superseded notes",
        })
    order = {"critical": 0, "warning": 1}
    alerts.sort(key=lambda a: order.get(a["severity"], 2))
    return alerts


def baseline_path(cfg) -> Path:
    return _store_dir(cfg) / "quality-baseline.json"


def pin(cfg, window: int = DEFAULT_WINDOW) -> dict:
    from loci import fsutil
    snap = snapshot(cfg, window)
    # atomic: a torn baseline reads as {} and every later compare screams drift
    fsutil.atomic_write(baseline_path(cfg),
                        json.dumps(snap, ensure_ascii=False, indent=2))
    return snap


def compare(cfg, window: int = DEFAULT_WINDOW) -> dict:
    current = snapshot(cfg, window)
    path = baseline_path(cfg)
    baseline = {}
    if path.exists():
        try:
            baseline = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            baseline = {}
    return {"current": current, "baseline": baseline,
            "alerts": drift(current, baseline), "baseline_path": str(path)}


def report(result: dict) -> str:
    cur, base = result["current"], result.get("baseline") or {}
    if not cur["queries"]:
        return ("(no query log yet — enable `[http] query_log = \"queries.jsonl\"` "
                "and use the console or `serve-http` a few times)")
    lines = [f"window: {cur['queries']} queries"]
    for key, label in (("zero_hit_rate", "zero-hit"), ("avg_hits", "avg hits"),
                       ("avg_ms", "avg ms"), ("p95_ms", "p95 ms"),
                       ("bad_rate", "bad-answer rate"),
                       ("feedback_coverage", "feedback coverage")):
        now = cur.get(key)
        was = base.get(key)
        arrow = ""
        if was is not None and now is not None and was != now:
            arrow = f"   (baseline {was})"
        lines.append(f"  {label:<20} {now}{arrow}")
    if not base:
        lines.append("\nno baseline pinned — run `loci quality --pin` on a known-good day,")
        lines.append("then `loci quality` reports drift against it.")
    alerts = result.get("alerts") or []
    if alerts:
        lines.append("")
        for a in alerts:
            lines.append(f"[{a['severity'].upper()}] {a['message']}")
            lines.append(f"   likely cause: {a['likely']}")
    elif base:
        lines.append("\nno drift against the pinned baseline")
    return "\n".join(lines)
