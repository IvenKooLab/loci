"""Watch mode: poll source directories and keep the index current. Pure
stdlib — a periodic rescan reuses the content-hash bookkeeping, so unchanged
files cost nothing and no filesystem driver is needed."""
from __future__ import annotations

import time
from datetime import datetime

from loci import chunker, config, loaders


def ingest_once(cfg) -> int:
    """One incremental pass. Returns the number of files re-indexed."""
    from loci.cli import build
    embedder, store = build(cfg)
    docs = loaders.scan_sources(cfg.sources)
    store.prune(keep={d["path"] for d in docs})
    changed = 0
    for doc in docs:
        if store.indexed_hash(doc["path"]) == doc["hash"]:
            continue
        size, overlap = chunker.params_for(doc, cfg.chunk)
        chunks = chunker.split_markdown(doc["content"], size, overlap)
        if not chunks:
            if store.indexed_hash(doc["path"]) is not None:
                store.delete_file(doc["path"])  # avoid stale chunks
            continue
        texts = [c["text"] for c in chunks]
        chashes, reuse = store.reuse_map(doc["path"], texts)
        missing = [i for i, h in enumerate(chashes) if h not in reuse]
        new_vecs = embedder.embed([texts[i] for i in missing]) if missing else []
        vectors = [None] * len(chunks)
        for i, h in enumerate(chashes):
            if h in reuse:
                vectors[i] = reuse[h]
        for i, v in zip(missing, new_vecs):
            vectors[i] = v
        store.upsert_chunks(chunks, vectors, doc["path"], doc["hash"],
                            doc["tags"], doc["links"], doc["mtime"],
                            chashes=chashes)
        changed += 1
        print(f"  [{_now()}] re-indexed: {doc['path']}")
    return changed


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def cmd_watch(cfg) -> None:
    interval = max(int(cfg.watch.get("interval", 30)), 5)
    auto_summarize = bool(cfg.watch.get("auto_summarize"))
    print(f"watching {len(cfg.sources)} source(s), every {interval}s"
          + (" + harness auto-summarize" if auto_summarize else "")
          + " — Ctrl+C to stop")
    while True:
        try:
            n = ingest_once(cfg)
            if n:
                print(f"  [{_now()}] {n} file(s) updated")
            if auto_summarize:
                _summarize_once(cfg)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            # never die on a single bad pass; report and keep watching
            print(f"  [{_now()}] ingest pass failed: {type(e).__name__}: {e}")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print(f"\n[{_now()}] watch stopped")
            return


def _summarize_once(cfg) -> None:
    """Refresh harness digests — fingerprint-gated, so an unchanged harness
    costs nothing and this is safe to run every cycle."""
    from loci import harness as harness_mod
    harnesses = harness_mod.load_harnesses(cfg)
    if not harnesses:
        return
    for r in harness_mod.summarize_all(cfg, harnesses, force=False):
        if r["status"] == "written":
            print(f"  [{_now()}] harness summary refreshed: {r['harness']}")
        elif r["status"] == "error":
            print(f"  [{_now()}] harness summary failed: {r['harness']} "
                  f"({r.get('error', '')})")
