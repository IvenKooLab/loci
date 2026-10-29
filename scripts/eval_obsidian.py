"""Offline regression evaluation for a synthetic Obsidian-style vault.

Run from a source checkout: python scripts/eval_obsidian.py
This uses a temporary Chroma index and deterministic token-hash vectors, not a
real embedding model. It measures exact file + heading + evidence at ranks 1/5;
it does not measure semantic quality, LLM answers, or production accuracy.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from loci import chunker, loaders  # noqa: E402
from loci.bm25 import tokenize  # noqa: E402
from loci.retriever import Retriever  # noqa: E402
from loci.store import Store  # noqa: E402

VAULT = ROOT / "tests/fixtures/obsidian-vault"
CASES = ROOT / "tests/fixtures/obsidian-cases.jsonl"


class TokenHashEmbedder:
    """Stable lexical test vectors; not a substitute for model evaluation."""
    def embed(self, texts, batch=16):
        vectors = []
        for text in texts:
            vec = [0.0] * 256
            for token in set(tokenize(text)):
                index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % len(vec)
                vec[index] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vectors.append([x / norm for x in vec])
        return vectors


def make_index(vault, db):
    store = Store(str(db))
    embedder = TokenHashEmbedder()
    for doc in loaders.scan_sources([{"path": str(vault)}]):
        chunks = chunker.split_markdown(doc["content"], 800, 100)
        if chunks:
            store.upsert_chunks(chunks, embedder.embed([c["text"] for c in chunks]),
                                doc["path"], doc["hash"], doc["tags"],
                                doc["links"], doc["mtime"])
    return Retriever(embedder, store, top_k=5, hybrid=True,
                     bm25_tokenizer="cjk_bigram")


def is_match(hit, case, vault):
    try:
        source = Path(hit["source"]).resolve().relative_to(Path(vault).resolve()).as_posix()
    except ValueError:
        return False
    return (source == case["source"] and hit["section"] == case["section"]
            and case["evidence"] in hit["text"])


def evaluate(retriever, vault, cases):
    rows = []
    for case in cases:
        hits = retriever.search(case["query"], k=5)
        rank = next((i for i, hit in enumerate(hits, 1)
                     if is_match(hit, case, vault)), None)
        rows.append({"query": case["query"], "rank": rank})
    return rows


def main():
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    with tempfile.TemporaryDirectory(prefix="loci-obsidian-eval-") as tmp:
        rows = evaluate(make_index(VAULT, Path(tmp) / "index"), VAULT, cases)
    for row in rows:
        print(f"rank={row['rank'] or 'miss'}  {row['query']}")
    print(f"exact evidence hit@1: {sum(r['rank'] == 1 for r in rows)}/{len(rows)}")
    print(f"exact evidence hit@5: {sum(r['rank'] is not None for r in rows)}/{len(rows)}")
    print("Synthetic fixture + token-hash vectors; not real-model or answer accuracy.")
    return 0 if rows and all(r["rank"] is not None for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
