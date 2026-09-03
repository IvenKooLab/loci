"""向量库：ChromaDB 持久化封装 + 增量记账（按文件内容 hash）。"""
from __future__ import annotations

import chromadb


class Store:
    def __init__(self, path: str):
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            "brain", metadata={"hnsw:space": "cosine"})

    # ---- 记账：文件级增量 ----

    def indexed_hash(self, path: str) -> str | None:
        got = self.collection.get(where={"source": path}, include=["metadatas"], limit=1)
        metas = got.get("metadatas") or []
        return metas[0].get("hash") if metas else None

    def delete_file(self, path: str) -> None:
        self.collection.delete(where={"source": path})

    # ---- 写入 ----

    def upsert_chunks(self, chunks: list[str], vectors: list[list[float]],
                      path: str, file_hash: str) -> None:
        self.delete_file(path)
        self.collection.add(
            ids=[f"{path}::{i}" for i in range(len(chunks))],
            documents=chunks, embeddings=vectors,
            metadatas=[{"source": path, "hash": file_hash, "chunk": i}
                       for i in range(len(chunks))])

    def count(self) -> int:
        return self.collection.count()

    # ---- 检索 ----

    def query(self, vector: list[float], top_k: int) -> list[dict]:
        got = self.collection.query(query_embeddings=[vector], n_results=top_k)
        hits = []
        for doc, meta, dist in zip(got["documents"][0], got["metadatas"][0],
                                   got["distances"][0]):
            hits.append({"text": doc, "source": meta["source"],
                         "chunk": meta["chunk"], "distance": round(dist, 4)})
        return hits
