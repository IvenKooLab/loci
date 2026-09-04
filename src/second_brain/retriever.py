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
                 hybrid: bool = True, rrf_k: int = 60,
                 rerank: bool = False, llm_cfg: dict | None = None):
        self.embedder, self.store, self.top_k = embedder, store, top_k
        self.hybrid, self.rrf_k = hybrid, rrf_k
        self.rerank, self.llm_cfg = rerank, llm_cfg

    def search(self, query: str, tag: str | None = None,
               rerank: bool | None = None) -> list[dict]:
        vec = self.embedder.embed([query])[0]
        # over-fetch so fusion and tag filtering still leave top_k results
        fetch = self.top_k * 4 if (self.hybrid or tag or rerank) else self.top_k
        vhits = self.store.query(vec, fetch)
        fused = self._fuse(vhits, query, fetch)
        if tag:
            t = tag.lower()
            fused = [h for h in fused if t in h["tags"].lower()]
        use_rerank = self.rerank if rerank is None else rerank
        if use_rerank and self.llm_cfg:
            fused = rerank_hits(self.llm_cfg, query, fused)
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


RERANK_PROMPT = (
    "You rank search candidates for a personal knowledge base. "
    "Given a query and numbered candidates, rate each candidate's relevance "
    "to the query from 0 (irrelevant) to 3 (directly answers it). "
    'Reply with ONLY a JSON array like [[0, 3], [1, 0], ...] — one pair per candidate.'
)


def rerank_hits(llm_cfg: dict, query: str, hits: list[dict]) -> list[dict]:
    """LLM-pointwise reranking. Fail-open: any error keeps the original order."""
    if len(hits) < 2:
        return hits
    try:
        client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
        listing = "\n\n".join(
            f"[{i}] {h['text'][:300]}" for i, h in enumerate(hits))
        resp = client.chat.completions.create(
            model=llm_cfg["model"],
            messages=[
                {"role": "system", "content": RERANK_PROMPT},
                {"role": "user", "content": f"Query: {query}\n\nCandidates:\n{listing}"},
            ],
            temperature=0.0,
        )
        import json
        pairs = json.loads(resp.choices[0].message.content or "[]")
        scores = {int(idx): float(s) for idx, s in pairs}
        if not scores:
            return hits
        return [h for _, _, h in sorted(
            ((scores.get(i, 0.0), -i, h) for i, h in enumerate(hits)),
            key=lambda t: (-t[0], t[1]))]
    except Exception:
        return hits


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
