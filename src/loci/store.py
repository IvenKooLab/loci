"""Vector store: ChromaDB persistence wrapper + incremental bookkeeping
(by file content hash) with real pruning of files that disappear."""
from __future__ import annotations

import json
import os

# chromadb's first init posts telemetry and can hang for minutes behind
# firewalls — off by default, this is a local-first tool
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb

from loci import bm25_cache


class Store:
    def __init__(self, path: str):
        self.path = path
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self._open_collection()

    def _open_collection(self):
        return self.client.get_or_create_collection(
            "brain", metadata={"hnsw:space": "cosine"})

    # ---- embedding fingerprint: one vector space per collection ----

    def _stamp(self, extra: dict) -> None:
        # hnsw:* keys belong to chroma internals: passing them through
        # modify() is rejected as a distance-function change even untouched
        meta = {k: v for k, v in (self.collection.metadata or {}).items()
                if not k.startswith("hnsw:")}
        meta.update(extra)
        self.collection.modify(metadata=meta)

    def ensure_embed(self, model: str, dim: int, rebuild: bool = False) -> None:
        """Guard the collection against a second embedding model: mixing vector
        spaces (different model or dimension) either crashes chroma or, when
        dimensions coincide, silently poisons retrieval quality."""
        if self.collection.count() == 0:
            self._stamp({"embed_model": model, "embed_dim": dim})
            return
        meta = self.collection.metadata or {}
        cur_model, cur_dim = meta.get("embed_model"), meta.get("embed_dim")
        if cur_model is None:
            # legacy collection (built before fingerprints existed): learn its
            # real dimension from stored vectors instead of trusting config,
            # which typically changed *because* the user is switching models
            got = self.collection.get(limit=1, include=["embeddings"])
            embs = got.get("embeddings")
            if embs is None or len(embs) == 0:
                embs = []
            cur_dim = len(embs[0]) if len(embs) else None
            if cur_dim is None or cur_dim == dim:
                # matching (or unreadable) dimension: assume the same model
                # and stamp the fingerprint for future runs
                self._stamp({"embed_model": model, "embed_dim": dim})
                return
            cur_model = "(unknown, pre-fingerprint)"
        elif cur_model == model and cur_dim in (None, dim):
            return
        if not rebuild:
            raise SystemExit(
                f"embedding model changed: index was built with {cur_model} "
                f"(dim {cur_dim}), config now has {model} (dim {dim}). "
                "Re-run with --force to rebuild the index from scratch.")
        self.client.delete_collection("brain")
        self.collection = self.client.get_or_create_collection(
            "brain", metadata={"hnsw:space": "cosine",
                               "embed_model": model, "embed_dim": dim})

    def reset(self) -> None:
        """Drop and recreate the collection."""
        self.client.delete_collection("brain")
        self.collection = self._open_collection()
        bm25_cache.bump(self.path)

    # ---- bookkeeping: per-file incrementality ----

    def indexed_hash(self, path: str) -> str | None:
        got = self.collection.get(where={"source": path}, include=["metadatas"], limit=1)
        metas = got.get("metadatas") or []
        return metas[0].get("hash") if metas else None

    def list_sources(self) -> set[str]:
        got = self.collection.get(include=["metadatas"])
        return {m["source"] for m in (got.get("metadatas") or [])}

    def delete_file(self, path: str) -> None:
        self.collection.delete(where={"source": path})
        bm25_cache.bump(self.path)

    def prune(self, keep: set[str]) -> list[str]:
        """Drop chunks of files no longer present in the sources. Returns removed paths."""
        removed = sorted(self.list_sources() - keep)
        for path in removed:
            self.delete_file(path)
        return removed

    # ---- writes ----

    def upsert_chunks(self, chunks: list[dict], vectors: list[list[float]],
                      path: str, file_hash: str,
                      tags: str = "", links: str = "", mtime: float = 0.0,
                      chashes: list[str] | None = None) -> None:
        """chunks: [{"text", "section"}] as produced by chunker.split_markdown.
        chashes: per-chunk content fingerprints (sha1[:16] of text), aligned with
        chunks — they let future re-indexes reuse vectors for unchanged chunks."""
        if chashes is None:
            chashes = [""] * len(chunks)
        self.delete_file(path)
        self.collection.add(
            ids=[f"{path}::{i}" for i in range(len(chunks))],
            documents=[c["text"] for c in chunks], embeddings=vectors,
            metadatas=[{"source": path, "hash": file_hash, "chunk": i,
                        "section": c.get("section", ""), "tags": tags,
                        "links": links, "mtime": mtime, "chash": chashes[i]}
                       for i, c in enumerate(chunks)])
        bm25_cache.bump(self.path)

    def dump(self, path: str) -> dict:
        """Write every chunk to a JSONL file for `loci import` (the native build).

        Chroma is not readable outside Python, so a migration is export-then-
        import rather than a shared file format. One JSON object per line keeps
        it streamable: a 100k-chunk index should not need 100k chunks resident
        in memory on either side.
        """
        from pathlib import Path as _P

        out = _P(path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        got = self.collection.get(include=["documents", "metadatas", "embeddings"])
        ids = got.get("ids") or []
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []
        embs = got.get("embeddings")
        tmp = out.with_suffix(out.suffix + ".part")
        n = 0
        with tmp.open("w", encoding="utf-8") as f:
            for i, cid in enumerate(ids):
                meta = dict(metas[i] or {})
                meta["id"] = cid
                meta["text"] = docs[i] if i < len(docs) else ""
                if embs is not None and i < len(embs):
                    meta["vec"] = [round(float(x), 6) for x in embs[i]]
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
                n += 1
            # the embedding space travels with the data: importing vectors built
            # by a different model would poison retrieval silently
            head = {"__meta__": {"chunks": n,
                                 "embed_model": (self.collection.metadata or {}).get("embed_model"),
                                 "embed_dim": (self.collection.metadata or {}).get("embed_dim")}}
            f.write(json.dumps(head) + "\n")
        tmp.replace(out)
        return {"path": str(out), "chunks": n}

    def count(self) -> int:
        return self.collection.count()

    # ---- retrieval ----

    def query(self, vector: list[float], top_k: int) -> list[dict]:
        got = self.collection.query(query_embeddings=[vector], n_results=max(top_k, 1),
                                    include=["documents", "metadatas", "distances"])
        if not got["ids"] or not got["ids"][0]:
            return []
        hits = []
        for cid, doc, meta, dist in zip(got["ids"][0], got["documents"][0],
                                        got["metadatas"][0], got["distances"][0]):
            hits.append({"id": cid, "text": doc, "source": meta["source"],
                         "chunk": meta["chunk"], "section": meta.get("section", ""),
                         "tags": meta.get("tags", ""), "links": meta.get("links", ""),
                         "mtime": meta.get("mtime", 0.0), "distance": round(dist, 4)})
        return hits

    def all_chunks(self) -> tuple[list[str], list[str]]:
        """(ids, documents) for every chunk in the store — feeds the BM25 side."""
        got = self.collection.get(include=["documents"])
        return list(got["ids"]), list(got["documents"])

    def get_many(self, ids: list[str]) -> list[dict]:
        got = self.collection.get(ids=ids, include=["documents", "metadatas"])
        hits = []
        for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"]):
            hits.append({"id": cid, "text": doc, "source": meta["source"],
                         "chunk": meta["chunk"], "section": meta.get("section", ""),
                         "tags": meta.get("tags", ""), "links": meta.get("links", ""),
                         "mtime": meta.get("mtime", 0.0), "distance": None})
        return hits

    def reuse_map(self, path: str, texts: list[str]) -> tuple[list[str], dict[str, list]]:
        """Fingerprint new chunk texts and fetch still-valid vectors for identical
        chunks already in the index. Returns (hashes, {hash: vector})."""
        import hashlib
        got = self.collection.get(where={"source": path},
                                  include=["metadatas", "embeddings"])
        old = {}
        metas = got.get("metadatas") or []
        embs = got.get("embeddings")
        if embs is None:
            embs = []
        for meta, emb in zip(metas, embs):
            if meta.get("chash") and emb is not None and len(emb) > 0:
                old[meta["chash"]] = [float(x) for x in emb]
        hashes = [hashlib.sha1(t.encode("utf-8")).hexdigest()[:16] for t in texts]
        return hashes, {h: old[h] for h in hashes if h in old}

    def per_source(self) -> dict[str, int]:
        got = self.collection.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for m in got.get("metadatas") or []:
            counts[m["source"]] = counts.get(m["source"], 0) + 1
        return dict(sorted(counts.items()))

    def link_map(self) -> dict[str, str]:
        """{source path: comma-joined outbound [[wikilink]] targets}."""
        got = self.collection.get(include=["metadatas"])
        out: dict[str, str] = {}
        for m in got.get("metadatas") or []:
            out.setdefault(m["source"], m.get("links", ""))
        return out

    def texts_of(self, path: str) -> list[str]:
        """All chunk texts of one source, in original order — feeds MCP resources."""
        got = self.collection.get(where={"source": path},
                                  include=["documents", "metadatas"])
        pairs = sorted(zip(got.get("metadatas") or [], got.get("documents") or []),
                       key=lambda m: m[0].get("chunk", 0))
        return [doc for _, doc in pairs]
