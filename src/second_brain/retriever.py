"""Retrieval: vector search fused with BM25 via Reciprocal Rank Fusion,
and grounded answer synthesis with cited sources."""
from __future__ import annotations

from openai import OpenAI

from second_brain.bm25 import BM25

SYSTEM_PROMPT = (
    "You are a Q&A assistant over the user's personal knowledge base. "
    "Answer only from the provided excerpts; if they don't contain the answer, "
    "say so plainly — do not invent. End your reply with a list of citations "
    "in the form [source: file path > section]."
)


class Retriever:
    def __init__(self, embedder, store, top_k: int,
                 hybrid: bool = True, rrf_k: int = 60):
        self.embedder, self.store, self.top_k = embedder, store, top_k
        self.hybrid, self.rrf_k = hybrid, rrf_k

    def search(self, query: str, tag: str | None = None) -> list[dict]:
        vec = self.embedder.embed([query])[0]
        # over-fetch so fusion and tag filtering still leave top_k results
        fetch = self.top_k * 4 if (self.hybrid or tag) else self.top_k
        vhits = self.store.query(vec, fetch)
        fused = self._fuse(vhits, query, fetch)
        if tag:
            t = tag.lower()
            fused = [h for h in fused if t in h["tags"].lower()]
        return fused[: self.top_k]

    def _fuse(self, vhits: list[dict], query: str, fetch: int) -> list[dict]:
        if not self.hybrid:
            return vhits
        ids, docs = self.store.all_chunks()
        if not ids:
            return vhits
        ranked = BM25(dict(zip(ids, docs))).score(query)[:fetch]
        scores: dict[str, float] = {}
        for r, h in enumerate(vhits):
            scores[h["id"]] = scores.get(h["id"], 0.0) + 1.0 / (self.rrf_k + r + 1)
        for r, (cid, _) in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (self.rrf_k + r + 1)
        by_id = {h["id"]: h for h in vhits}
        missing = [cid for cid, _ in ranked if cid not in by_id]
        if missing:
            by_id.update({h["id"]: h for h in self.store.get_many(missing)})
        ordered = sorted(scores.items(), key=lambda kv: -kv[1])[: self.top_k * 4]
        return [by_id[cid] for cid, _ in ordered if cid in by_id]


def answer(llm_cfg: dict, question: str, hits: list[dict],
           history: list[dict] | None = None) -> str:
    context = "\n\n---\n\n".join(
        f"[chunk {i + 1} | source: {h['source']}"
        + (f" | section: {h['section']}" if h.get("section") else "")
        + f"]\n{h['text']}"
        for i, h in enumerate(hits))
    client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user",
                     "content": f"Excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"})
    resp = client.chat.completions.create(
        model=llm_cfg["model"], messages=messages, temperature=0.3)
    return resp.choices[0].message.content or ""
