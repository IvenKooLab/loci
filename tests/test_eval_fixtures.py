"""The eval fixtures must stay sound, or the regression gate lies.

Every case's `expect` must match exactly one corpus file — a stale filename
would silently score as a permanent miss, and a duplicated match would make
the metric meaningless. No index needed: this is a static check.
"""
from __future__ import annotations

import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "retrieval-eval"
CORPUS = FIX / "corpus"
CASES = FIX / "cases.jsonl"


def test_every_expect_matches_exactly_one_corpus_file():
    files = sorted(p.name for p in CORPUS.glob("*.md"))
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(cases) >= 20, "eval set too small to be a meaningful gate"
    for case in cases:
        hits = [f for f in files if case["expect"] in f]
        assert len(hits) == 1, (
            f"{case['expect']!r} matches {hits} — must match exactly one file")


def test_every_corpus_file_is_targeted_at_least_once():
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    covered = {c["expect"] for c in cases}
    for f in sorted(CORPUS.glob("*.md")):
        assert f.name in covered, f"{f.name} has no case — dead corpus file"


def test_queries_cover_both_languages():
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    zh = sum(1 for c in cases if any("\u4e00" <= ch <= "\u9fff" for ch in c["query"]))
    en = len(cases) - zh
    assert zh >= 8 and en >= 8, f"expected a real mix, got zh={zh} en={en}"
