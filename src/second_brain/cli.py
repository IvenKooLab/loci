"""CLI: ingest / search / ask / stats / doctor."""
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


def make_retriever(cfg, embedder, store):
    from second_brain.retriever import Retriever
    return Retriever(embedder, store, cfg.top_k["search"],
                     hybrid=cfg.retrieval["hybrid"], rrf_k=cfg.retrieval["rrf_k"])


def cmd_ingest(cfg, force: bool = False) -> None:
    embedder, store = build(cfg)
    docs = loaders.scan_sources(cfg.sources)
    removed = store.prune(keep={d["path"] for d in docs})
    for path in removed:
        print(f"  - pruned (file gone): {path}")
    if not docs:
        print("No .md/.txt documents found — check the sources entries in config.toml")
        return
    added = updated = skipped = 0
    for doc in docs:
        if not force and store.indexed_hash(doc["path"]) == doc["hash"]:
            skipped += 1
            continue
        if store.indexed_hash(doc["path"]) is not None:
            updated += 1
        else:
            added += 1
        chunks = chunker.split_markdown(doc["content"],
                                        cfg.chunk["size"], cfg.chunk["overlap"])
        if not chunks:
            continue
        vectors = embedder.embed([c["text"] for c in chunks])
        store.upsert_chunks(chunks, vectors, doc["path"], doc["hash"], doc["tags"])
        print(f"  + {Path(doc['path']).name}: {len(chunks)} chunks")
    mode = " (forced)" if force else ""
    print(f"Done{mode}: {added} added / {updated} updated / {skipped} unchanged — "
          f"{store.count()} chunks in store")


def cmd_search(cfg, query: str, tag: str | None = None) -> None:
    embedder, store = build(cfg)
    hits = make_retriever(cfg, embedder, store).search(query, tag=tag)
    if not hits:
        print("(no results)")
        return
    for i, h in enumerate(hits, 1):
        where = f" > {h['section']}" if h["section"] else ""
        sim = f"similarity {1 - h['distance']:.3f}" if h["distance"] is not None else "hybrid hit"
        print(f"[{i}] {h['source']}{where}  ({sim})")
        print(f"    {h['text'][:120].replace(chr(10), ' ')}...")


def cmd_ask(cfg, question: str) -> None:
    from second_brain.retriever import Retriever, answer
    embedder, store = build(cfg)
    hits = make_retriever(cfg, embedder, store).search(question)
    if not hits:
        print("(nothing relevant in the knowledge base)")
        return
    print("Answer:\n")
    print(answer(cfg.llm, question, hits))


def cmd_chat(cfg) -> None:
    from second_brain.retriever import answer
    embedder, store = build(cfg)
    retriever = make_retriever(cfg, embedder, store)
    history: list[dict] = []
    print("chat — ask your knowledge base; /clear resets context, /exit quits")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not q:
            continue
        if q in ("/exit", "/quit"):
            return
        if q == "/clear":
            history.clear()
            print("(context cleared)")
            continue
        hits = retriever.search(q)
        if not hits:
            print("brain> (nothing relevant in the knowledge base)")
            continue
        reply = answer(cfg.llm, q, hits, history=history)
        history.extend([{"role": "user", "content": q},
                        {"role": "assistant", "content": reply}])
        del history[:-8]  # keep the last four turns
        print(f"brain> {reply}\n")


def cmd_watch(cfg) -> None:
    from second_brain.watcher import cmd_watch as watch
    watch(cfg)


def cmd_stats(cfg) -> None:
    _, store = build(cfg)
    hybrid = "on" if cfg.retrieval["hybrid"] else "off"
    print(f"store      : {cfg.store['path']}  ({store.count()} chunks)")
    print(f"models     : {cfg.embed['model']} (embed) / {cfg.llm['model']} (llm)")
    print(f"retrieval  : hybrid {hybrid} (rrf_k={cfg.retrieval['rrf_k']}), "
          f"top_k={cfg.top_k['search']}")
    per_source = store.per_source()
    if not per_source:
        print("sources    : (index is empty — run `ingest` first)")
        return
    width = max(len(p) for p in per_source)
    print("sources    :")
    for path, n in per_source.items():
        print(f"  {path:<{width}}  {n:>5} chunks")


def cmd_doctor(cfg) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("config file", Path("config.toml").exists(),
                   "config.toml found" if Path("config.toml").exists()
                   else "config.toml missing (cp config.example.toml config.toml)"))
    for name, section in (("llm key", cfg.llm), ("embed key", cfg.embed)):
        checks.append((name, bool(section.get("api_key")),
                       "configured" if section.get("api_key") else "missing"))
    for src in cfg.sources:
        from pathlib import Path as P
        ok = P(src["path"]).expanduser().exists()
        checks.append(("source dir", ok, src["path"]))

    try:
        import chromadb  # noqa: F401
        checks.append(("chromadb import", True, chromadb.__version__))
    except Exception as e:  # pragma: no cover
        checks.append(("chromadb import", False, str(e)))

    if cfg.embed.get("api_key"):
        try:
            embedder, store = build(cfg)
            dim = len(embedder.embed(["ping"])[0])
            checks.append(("embed endpoint", True, f"reachable, dim={dim}"))
            checks.append(("vector store", True, f"{store.count()} chunks"))
        except Exception as e:
            checks.append(("embed endpoint", False, str(e)[:120]))
    if cfg.llm.get("api_key"):
        try:
            from openai import OpenAI
            client = OpenAI(base_url=cfg.llm["base_url"], api_key=cfg.llm["api_key"])
            r = client.chat.completions.create(
                model=cfg.llm["model"],
                messages=[{"role": "user", "content": "ping"}], max_tokens=1)
            checks.append(("llm endpoint", bool(r),
                           f"{cfg.llm['model']} reachable"))
        except Exception as e:
            checks.append(("llm endpoint", False, str(e)[:120]))

    failed = 0
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        if not ok:
            failed += 1
        print(f"  {mark} {name:<16} {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed"
          + ("" if not failed else " — fix the ✗ items above"))
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="second-brain-rag — Q&A over your personal knowledge base")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="scan source directories and incrementally index them")
    p_ingest.add_argument("--force", action="store_true",
                          help="re-embed everything, ignoring content hashes")

    p_search = sub.add_parser("search", help="retrieval only (no LLM call)")
    p_search.add_argument("query")
    p_search.add_argument("--tag", help="filter hits by frontmatter tag")
    p_search.add_argument("-k", type=int, help="override top_k")

    p_ask = sub.add_parser("ask", help="retrieval + LLM answer with citations")
    p_ask.add_argument("question")
    p_ask.add_argument("-k", type=int, help="override top_k")

    sub.add_parser("chat", help="multi-turn Q&A loop with conversation memory")
    sub.add_parser("watch", help="keep the index current by polling sources")
    sub.add_parser("stats", help="show what is in the index")
    sub.add_parser("doctor", help="check config, endpoints, and store health")

    args = parser.parse_args()
    cfg = config.load()
    if getattr(args, "k", None):
        cfg.top_k["search"] = args.k

    if args.cmd == "ingest":
        cfg.validate()
        cmd_ingest(cfg, force=args.force)
    elif args.cmd == "search":
        cfg.validate()
        cmd_search(cfg, args.query, tag=args.tag)
    elif args.cmd == "ask":
        cfg.validate()
        cmd_ask(cfg, args.question)
    elif args.cmd == "chat":
        cfg.validate()
        cmd_chat(cfg)
    elif args.cmd == "watch":
        cfg.validate()
        cmd_watch(cfg)
    elif args.cmd == "stats":
        cmd_stats(cfg)
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(cfg))


if __name__ == "__main__":
    main()
