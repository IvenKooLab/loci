"""CLI: ingest / search / ask."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from second_brain import config, loaders, chunker  # noqa: E402


def build(cfg):
    from second_brain.embedder import Embedder
    from second_brain.store import Store
    return Embedder(cfg.embed["base_url"], cfg.embed["api_key"], cfg.embed["model"]), \
        Store(cfg.store["path"])


def cmd_ingest(cfg) -> None:
    embedder, store = build(cfg)
    docs = loaders.scan_sources(cfg.sources)
    if not docs:
        print("No .md/.txt documents found — check the sources entries in config.toml")
        return
    added = updated = skipped = 0
    for doc in docs:
        old = store.indexed_hash(doc["path"])
        if old == doc["hash"]:
            skipped += 1
            continue
        if old is not None:
            updated += 1
        else:
            added += 1
        chunks = chunker.split_markdown(doc["content"],
                                        cfg.chunk["size"], cfg.chunk["overlap"])
        if not chunks:
            continue
        vectors = embedder.embed(chunks)
        store.upsert_chunks(chunks, vectors, doc["path"], doc["hash"])
        print(f"  + {Path(doc['path']).name}: {len(chunks)} chunks")
    print(f"Done: {added} added / {updated} updated / {skipped} unchanged — "
          f"{store.count()} chunks in store")


def cmd_search(cfg, query: str) -> None:
    embedder, store = build(cfg)
    from second_brain.retriever import Retriever
    hits = Retriever(embedder, store, cfg.top_k["search"]).search(query)
    if not hits:
        print("(no results)")
        return
    for i, h in enumerate(hits, 1):
        print(f"[{i}] {h['source']}  (similarity {1 - h['distance']:.3f})")
        print(f"    {h['text'][:120].replace(chr(10), ' ')}...")


def cmd_ask(cfg, question: str) -> None:
    from second_brain.embedder import Embedder
    from second_brain.retriever import Retriever, answer
    embedder, store = build(cfg)
    hits = Retriever(embedder, store, cfg.top_k["search"]).search(question)
    if not hits:
        print("(nothing relevant in the knowledge base)")
        return
    print("Answer:\n")
    print(answer(cfg.llm, question, hits))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="second-brain-rag — Q&A over your personal knowledge base")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="scan source directories and incrementally index them")
    p_search = sub.add_parser("search", help="retrieval only (no LLM call)")
    p_search.add_argument("query")
    p_ask = sub.add_parser("ask", help="retrieval + LLM answer with citations")
    p_ask.add_argument("question")
    args = parser.parse_args()

    cfg = config.load()
    if args.cmd == "ingest":
        cfg.validate()
        cmd_ingest(cfg)
    elif args.cmd == "search":
        cfg.validate()
        cmd_search(cfg, args.query)
    elif args.cmd == "ask":
        cfg.validate()
        cmd_ask(cfg, args.question)


if __name__ == "__main__":
    main()
