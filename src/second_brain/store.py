"""Vector store: ChromaDB persistence wrapper + incremental bookkeeping
(by file content hash) with real pruning of files that disappear."""
from __future__ import annotations

import chromadb


class Store:
    def __init__(self, path: str):
        self.path = path
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            "brain", metadata={"hnsw:space": "cosine"})

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

    def prune(self, keep: set[str]) -> list[str]:
        """Drop chunks of files no longer present in the sources. Returns removed paths."""
        removed = sorted(self.list_sources() - keep)
        for path in removed:
            self.delete_file(path)
        return removed

    # ---- writes ----

    def upsert_chunks(self, chunks: list[dict], vectors: list[list[float]],
                      path: str, file_hash: str, tags: str = "") -> None:
        """chunks: [{"text", "section"}] as produced by chunker.split_markdown."""
        self.delete_file(path)
        self.collection.add(
            ids=[f"{path}::{i}" for i in range(len(chunks))],
            documents=[c["text"] for c in chunks], embeddings=vectors,
            metadatas=[{"source": path, "hash": file_hash, "chunk": i,
                        "section": c.get("section", ""), "tags": tags}
                       for i, c in enumerate(chunks)])

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
                         "tags": meta.get("tags", ""), "distance": round(dist, 4)})
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
                         "tags": meta.get("tags", ""), "distance": None})
        return hits

    def per_source(self) -> dict[str, int]:
        got = self.collection.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for m in got.get("metadatas") or []:
            counts[m["source"]] = counts.get(m["source"], 0) + 1
        return dict(sorted(counts.items()))
