"""Retrieval regression gate: recall@k over a fixed eval set.

Changing retrieval parameters (rrf_k, top_k, tokenizer, fusion) used to land
with tests green and quality unknown — the unit tests pin behavior, not
ranking. This script pins ranking: a fixed corpus + fixed cases, scored
offline with deterministic token-hash vectors, compared against a committed
baseline. CI fails if any metric drops.

Honest about what it is: hash vectors are not a real embedding model, so
absolute numbers are not product quality. What they are is *stable* — any
change that moves recall@k moved it for a reason you can find in the diff.

Usage:
    python scripts/eval_retrieval.py                 # gate: fail on regression
    python scripts/eval_retrieval.py --update-baseline   # after a deliberate change
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# reuse the Obsidian eval's embedder/index helpers verbatim — two copies of
# "deterministic test vectors" would drift, and then they would lie
_spec = importlib.util.spec_from_file_location(
    "obsidian_eval", ROOT / "scripts" / "eval_obsidian.py")
_obsidian_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_obsidian_eval)

CORPUS = ROOT / "tests" / "fixtures" / "retrieval-eval" / "corpus"
CASES = ROOT / "tests" / "fixtures" / "retrieval-eval" / "cases.jsonl"
BASELINE = ROOT / "scripts" / "eval_retrieval.baseline.json"

METRICS = ("recall_at_1", "recall_at_5", "mrr")
TOLERANCE = 1e-9      # deterministic vectors: any real drop is a real drop


def load_cases() -> list[dict]:
    return [json.loads(line) for line in
            CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def score(k: int = 5) -> dict[str, float]:
    cases = load_cases()
    with tempfile.TemporaryDirectory(prefix="loci-retrieval-eval-") as tmp:
        retriever = _obsidian_eval.make_index(CORPUS, Path(tmp) / "index")
        ranks = []
        for case in cases:
            hits = retriever.search(case["query"], k=k)
            rank = next((i for i, hit in enumerate(hits, 1)
                         if case["expect"] in str(hit["source"])), None)
            ranks.append(rank)
    n = len(ranks)
    return {
        "recall_at_1": sum(r == 1 for r in ranks) / n,
        "recall_at_5": sum(r is not None for r in ranks) / n,
        "mrr": sum((1.0 / r if r else 0.0) for r in ranks) / n,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-baseline", action="store_true",
                        help="write current scores as the new baseline")
    parser.add_argument("--verbose", action="store_true",
                        help="print per-case ranks")
    args = parser.parse_args()

    current = score()
    for name, value in current.items():
        print(f"{name:>12}: {value:.4f}")

    if args.update_baseline:
        BASELINE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"baseline updated -> {BASELINE.name}")
        return 0

    if not BASELINE.exists():
        # first run on a machine: refuse to gate on nothing
        print(f"no baseline at {BASELINE} — run with --update-baseline first")
        return 2

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    regressions = [name for name in METRICS
                   if current[name] < baseline.get(name, 0.0) - TOLERANCE]
    if regressions:
        print("\nRETRIEVAL REGRESSION — the eval set got worse:")
        for name in regressions:
            print(f"  {name}: {baseline[name]:.4f} -> {current[name]:.4f}")
        print("\nIf the change is deliberate and reviewed, update the baseline:")
        print("  python scripts/eval_retrieval.py --update-baseline")
        return 1
    print("no regression against baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
