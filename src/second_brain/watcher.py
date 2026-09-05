"""Watch mode: poll source directories and keep the index current. Pure
stdlib — a periodic rescan reuses the content-hash bookkeeping, so unchanged
files cost nothing and no filesystem driver is needed."""
from __future__ import annotations

import time
from datetime import datetime

from second_brain import chunker, config, loaders


def ingest_once(cfg) -> int:
    """One incremental pass. Returns the number of files re-indexed."""
    from second_brain.cli import build
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
            continue
        vectors = embedder.embed([c["text"] for c in chunks])
        store.upsert_chunks(chunks, vectors, doc["path"], doc["hash"],
                            doc["tags"], doc["links"], doc["mtime"])
        changed += 1
        print(f"  [{_now()}] re-indexed: {doc['path']}")
    return changed


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def cmd_watch(cfg) -> None:
    interval = max(int(cfg.watch.get("interval", 30)), 5)
    print(f"watching {len(cfg.sources)} source(s), every {interval}s — Ctrl+C to stop")
    while True:
        try:
            n = ingest_once(cfg)
            if n:
                print(f"  [{_now()}] {n} file(s) updated")
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
