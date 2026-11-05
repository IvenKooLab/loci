"""Citation ledger and memory health — make adoption visible.

A memory note that is never cited is doing no work; one that keeps getting
corrected (`loci feedback bad`) is doing negative work. Until now neither was
observable: forget was purely manual and blind. The ledger records, for every
memory note a search or answer actually used, one line per note per query;
the health report joins it with the feedback log and the note's age.

Boundary, stated plainly: loci sees tool calls, not your conversation, so a
correction reaches it only through explicit feedback. The report surfaces
corrections and dead weight; it does not silently rewrite retrieval — that
already happens one layer down, where `bad` feedback sinks chunks.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

STALE_DAYS = 30          # uncited for a month → candidate for review


def _ledger_path(cfg) -> Path:
    return (cfg.store and Path(cfg.store.get("path", "./chroma_db")) or Path("./chroma_db")) / "citations.jsonl"


def record_citations(cfg, sources: list[str], query: str, via: str = "search") -> None:
    """Append one ledger line per memory source used by a query.

    Never raises: the ledger is instrumentation, and instrumentation that can
    break a search is worse than no instrumentation.
    """
    if not sources:
        return
    try:
        path = _ledger_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": time.time(), "via": via, "query": query[:200]}
        with path.open("a", encoding="utf-8") as f:
            for src in dict.fromkeys(sources):      # dedupe, keep order
                f.write(json.dumps({**line, "source": src}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_citations(cfg) -> dict[str, dict]:
    """{source: {count, last_ts, queries[last 3]}} from the ledger."""
    path = _ledger_path(cfg)
    out: dict[str, dict] = {}
    if not path.is_file():
        return out
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        try:
            rec = json.loads(raw)
            src = rec.get("source")
            if not src:
                continue
            e = out.setdefault(src, {"count": 0, "last_ts": 0.0, "queries": []})
            e["count"] += 1
            e["last_ts"] = max(e["last_ts"], float(rec.get("ts", 0)))
            if rec.get("query"):
                e["queries"] = (e["queries"] + [rec["query"]])[-3:]
        except (ValueError, TypeError):
            continue                       # a torn line must not kill the report
    return out


def load_corrections(cfg) -> dict[str, int]:
    """{source: correction_count} — `bad` verdicts from feedback.jsonl.

    Feedback is recorded per chunk id (`path::i`); the source is the part
    before the last `::`.
    """
    fb = Path(cfg.store.get("path", "./chroma_db")) / "feedback.jsonl"
    out: dict[str, int] = {}
    if not fb.is_file():
        return out
    try:
        for raw in fb.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if rec.get("verdict") != "bad":
                continue
            cid = str(rec.get("chunk_id", ""))
            src = cid.rsplit("::", 1)[0]
            if src:
                out[src] = out.get(src, 0) + 1
    except OSError:
        pass
    return out


def health(cfg) -> list[dict]:
    """One row per memory note: adoption and decay, with honest flags."""
    mem_dir = Path((cfg.memories or {}).get("path", "./memories")).expanduser()
    cited = load_citations(cfg)
    corrected = load_corrections(cfg)
    now = time.time()
    rows: list[dict] = []
    if not mem_dir.is_dir():
        return rows
    for path in sorted(mem_dir.glob("*.md")):
        try:
            stat = path.stat()
        except OSError:
            continue
        src = str(path.resolve())
        c = cited.get(src, {"count": 0, "last_ts": 0.0, "queries": []})
        age_days = max(0.0, (now - stat.st_mtime) / 86400)
        corrections = corrected.get(src, 0)
        flags = []
        if corrections:
            flags.append("corrected")
        if c["count"] == 0 and age_days >= STALE_DAYS:
            flags.append("never-cited")
        rows.append({
            "file": path.name, "bytes": stat.st_size,
            "age_days": round(age_days, 1),
            "citations": c["count"],
            "last_cited_days_ago": (round((now - c["last_ts"]) / 86400, 1)
                                    if c["last_ts"] else None),
            "corrections": corrections,
            "recent_queries": c["queries"],
            "flags": flags,
        })
    # most-worked first; dead weight sinks to the bottom
    rows.sort(key=lambda r: (-r["citations"], -r["corrections"], r["file"]))
    return rows
