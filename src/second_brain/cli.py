"""CLI：ingest / search / ask。"""
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
        print("没有扫到任何 .md/.txt 文档，检查 config.toml 的 sources")
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
        print(f"  + {Path(doc['path']).name}: {len(chunks)} 片段")
    print(f"完成: 新增 {added} / 更新 {updated} / 未变 {skipped}，"
          f"库中共 {store.count()} 片段")


def cmd_search(cfg, query: str) -> None:
    embedder, store = build(cfg)
    from second_brain.retriever import Retriever
    hits = Retriever(embedder, store, cfg.top_k["search"]).search(query)
    if not hits:
        print("（无结果）")
        return
    for i, h in enumerate(hits, 1):
        print(f"[{i}] {h['source']}  (相似度 {1 - h['distance']:.3f})")
        print(f"    {h['text'][:120].replace(chr(10), ' ')}...")


def cmd_ask(cfg, question: str) -> None:
    from second_brain.embedder import Embedder
    from second_brain.retriever import Retriever, answer
    embedder, store = build(cfg)
    hits = Retriever(embedder, store, cfg.top_k["search"]).search(question)
    if not hits:
        print("（知识库里没有相关内容）")
        return
    print("回答:\n")
    print(answer(cfg.llm, question, hits))


def main() -> None:
    parser = argparse.ArgumentParser(description="second-brain-rag 个人知识库问答")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="扫描目录，增量灌入知识库")
    p_search = sub.add_parser("search", help="纯检索（不调 LLM）")
    p_search.add_argument("query")
    p_ask = sub.add_parser("ask", help="检索 + LLM 回答")
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
