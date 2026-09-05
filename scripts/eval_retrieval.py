"""Tiny retrieval eval: hit@5 for vector-only vs hybrid retrieval.

Usage:
    python scripts/eval_retrieval.py cases.jsonl

Each line of cases.jsonl: {"query": "...", "expect": "substring of the
relevant file's path"} — e.g. {"query": "T8 speedup", "expect": "08-t8"}.

Prints a per-query comparison and a summary line. Read-only: never indexes.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci import config  # noqa: E402
from loci.cli import build, make_retriever  # noqa: E402


def _run_variant(retriever, hybrid, cases, k=5):
    retriever.hybrid = hybrid
    ok = 0
    for case in cases:
        hits = retriever.search(case["query"])[:k]
        good = any(case["expect"].lower() in h["source"].lower() for h in hits)
        ok += good
        top1 = hits[0]["source"].replace("\\", "/").split("/")[-1] if hits else "-"
        print(f"  {'✓' if good else '✗'} {case['query'][:48]:<50} top1={top1}")
    return ok, len(cases)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cases = [json.loads(l) for l in
             Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not cases:
        print("no eval cases found")
        return

    cfg = config.load()
    embedder, store = build(cfg)
    retriever = make_retriever(cfg, embedder, store)

    print(f"eval: {sys.argv[1]} — hit@5 across {len(cases)} queries\n")
    print("vector-only (hybrid off):")
    v_ok, n = _run_variant(retriever, False, cases)
    print("\nhybrid (vector + BM25, RRF fusion):")
    h_ok, _ = _run_variant(retriever, True, cases)
    print(f"\nsummary: vector-only {v_ok}/{n}  →  hybrid {h_ok}/{n}")


if __name__ == "__main__":
    main()
