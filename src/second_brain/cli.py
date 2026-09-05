"""CLI: ingest / search / ask / links / chat / watch / stats / doctor."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from second_brain import config, loaders, chunker  # noqa: E402


def parse_since(text: str) -> float:
    """Accept YYYY-MM-DD or YYYY-MM; return epoch seconds (raises on garbage)."""
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
    raise ValueError(f"bad --since value '{text}' (use YYYY-MM-DD or YYYY-MM)")


def build(cfg):
    from second_brain.embedder import Embedder
    from second_brain.store import Store
    return Embedder(cfg.embed["base_url"], cfg.embed["api_key"], cfg.embed["model"]), \
        Store(cfg.store["path"])


def make_retriever(cfg, embedder, store):
    from second_brain.retriever import Retriever
    return Retriever(embedder, store, cfg.top_k["search"],
                     hybrid=cfg.retrieval["hybrid"], rrf_k=cfg.retrieval["rrf_k"],
                     rerank=cfg.retrieval.get("rerank", False), llm_cfg=cfg.llm)


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
        store.upsert_chunks(chunks, vectors, doc["path"], doc["hash"],
                            doc["tags"], doc["links"], doc["mtime"])
        print(f"  + {Path(doc['path']).name}: {len(chunks)} chunks")
    mode = " (forced)" if force else ""
    print(f"Done{mode}: {added} added / {updated} updated / {skipped} unchanged — "
          f"{store.count()} chunks in store")


def cmd_search(cfg, query: str, tag: str | None = None, rerank: bool | None = None,
               path_contains: str | None = None, since: float | None = None,
               exact: str | None = None) -> None:
    embedder, store = build(cfg)
    hits = make_retriever(cfg, embedder, store).search(
        query, tag=tag, rerank=rerank, path_contains=path_contains,
        since=since, exact=exact)
    if not hits:
        print("(no results)")
        return
    for i, h in enumerate(hits, 1):
        where = f" > {h['section']}" if h["section"] else ""
        sim = f"similarity {1 - h['distance']:.3f}" if h["distance"] is not None else "hybrid hit"
        print(f"[{i}] {h['source']}{where}  ({sim})")
        print(f"    {h['text'][:120].replace(chr(10), ' ')}...")


def cmd_ask(cfg, question: str, rerank: bool | None = None,
            path_contains: str | None = None, since: float | None = None,
            verify: bool = False) -> None:
    from second_brain.retriever import Retriever, answer, verify_answer
    embedder, store = build(cfg)
    retriever = make_retriever(cfg, embedder, store)
    hits = retriever.search(question, rerank=rerank,
                            path_contains=path_contains, since=since)
    if not hits:
        print("(nothing relevant in the knowledge base)")
        return
    print("Answer:\n")
    reply = answer(cfg.llm, question, hits)
    print(reply)
    if verify:
        print("\n" + verify_answer(cfg.llm, question, reply, hits))


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


def cmd_links(cfg, name: str) -> None:
    _, store = build(cfg)
    graph = store.link_map()

    def note_stem(path: str) -> str:
        return Path(path).stem.lower()

    matches = [p for p in graph if name.lower() in note_stem(p) or name.lower() == note_stem(p)]
    if not matches:
        matches = [p for p, links in graph.items()
                   if any(name.lower() in t.lower() for t in links.split(",") if t)]
    if not matches:
        print(f"(no note matching '{name}' in the index)")
        return
    for path in matches:
        outbound = [t for t in graph.get(path, "").split(",") if t]
        stem = note_stem(path)
        inbound = [p for p, links in graph.items() if p != path and any(
            stem in t.lower() for t in links.split(",") if t)]
        print(f"{path}")
        if outbound:
            print("  links to:")
            for t in outbound:
                print(f"    -> {t}")
        if inbound:
            print("  linked from:")
            for p in sorted(inbound):
                print(f"    <- {p}")
        if not outbound and not inbound:
            print("  (no links either way)")


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

    from second_brain import loaders
    if loaders.HAS_PDF:
        checks.append(("pdf support", True, "pypdf installed"))
    else:
        checks.append(("pdf support", None,
                       "pypdf not installed — .pdf sources are skipped "
                       "(pip install 'second-brain-rag[pdf]')"))

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
        if ok is None:  # advisory, not a failure
            mark = "i"
        else:
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
    p_search.add_argument("--in", dest="path_contains", metavar="PATH",
                          help="only hits whose source path contains this substring")
    p_search.add_argument("--since", metavar="DATE", type=parse_since,
                          help="only files modified on/after DATE (YYYY-MM-DD or YYYY-MM)")
    p_search.add_argument("-e", "--exact", metavar="PHRASE",
                          help="only hits containing this exact phrase")
    p_search.add_argument("-k", type=int, help="override top_k")
    p_search.add_argument("--rerank", action="store_true",
                          help="LLM-rerank candidates before returning them")

    p_ask = sub.add_parser("ask", help="retrieval + LLM answer with citations")
    p_ask.add_argument("question")
    p_ask.add_argument("--in", dest="path_contains", metavar="PATH",
                       help="scope retrieval to paths containing this substring")
    p_ask.add_argument("--since", metavar="DATE", type=parse_since,
                       help="only files modified on/after DATE (YYYY-MM-DD or YYYY-MM)")
    p_ask.add_argument("-k", type=int, help="override top_k")
    p_ask.add_argument("--rerank", action="store_true",
                       help="LLM-rerank candidates before answering")
    p_ask.add_argument("--verify", action="store_true",
                       help="audit the answer claim-by-claim against the sources")

    p_links = sub.add_parser("links", help="show [[wikilink]] outbound/inbound links for a note")
    p_links.add_argument("note", help="note name (stem) to look up")

    sub.add_parser("chat", help="multi-turn Q&A loop with conversation memory")
    sub.add_parser("watch", help="keep the index current by polling sources")
    sub.add_parser("serve", help="run the MCP server over stdio (alias for mcp_server.py)")
    sub.add_parser("stats", help="show what is in the index")
    sub.add_parser("doctor", help="check config, endpoints, and store health")

    args = parser.parse_args()
    cfg = config.load()
    if getattr(args, "k", None):
        cfg.top_k["search"] = args.k
    wants_rerank = getattr(args, "rerank", False)
    wants_verify = getattr(args, "verify", False)

    if args.cmd == "ingest":
        cfg.validate()
        cmd_ingest(cfg, force=args.force)
    elif args.cmd == "search":
        cfg.validate()
        cmd_search(cfg, args.query, tag=args.tag, rerank=wants_rerank or None,
                   path_contains=args.path_contains, since=args.since,
                   exact=args.exact)
    elif args.cmd == "ask":
        cfg.validate()
        cmd_ask(cfg, args.question, rerank=wants_rerank or None,
                path_contains=args.path_contains, since=args.since,
                verify=wants_verify)
    elif args.cmd == "chat":
        cfg.validate()
        cmd_chat(cfg)
    elif args.cmd == "links":
        cmd_links(cfg, args.note)
    elif args.cmd == "watch":
        cfg.validate()
        cmd_watch(cfg)
    elif args.cmd == "serve":
        from second_brain.mcp_server import serve
        serve()
    elif args.cmd == "stats":
        cmd_stats(cfg)
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(cfg))


if __name__ == "__main__":
    main()
