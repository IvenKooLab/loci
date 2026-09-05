"""Retrieval: vector search fused with BM25 via Reciprocal Rank Fusion,
LLM reranking and answer verification, and grounded answer synthesis."""
from __future__ import annotations

import json

from openai import OpenAI

from loci.bm25 import BM25
from loci.reranker import local_rerank

SYSTEM_PROMPT = (
    "You are a Q&A assistant over the user's personal knowledge base. "
    "Answer only from the provided excerpts; if they don't contain the answer, "
    "say so plainly — do not invent. End your reply with a list of citations "
    "in the form [source: file path > section]."
)


class Retriever:
    def __init__(self, embedder, store, top_k: int,
                 hybrid: bool = True, rrf_k: int = 60,
                 rerank: bool = False, llm_cfg: dict | None = None,
                 rerank_provider: str = "llm",
                 local_rerank_model: str = "BAAI/bge-reranker-base"):
        self.embedder, self.store, self.top_k = embedder, store, top_k
        self.hybrid, self.rrf_k = hybrid, rrf_k
        self.rerank, self.llm_cfg = rerank, llm_cfg
        self.rerank_provider = rerank_provider
        self.local_rerank_model = local_rerank_model

    def search(self, query: str, tag: str | None = None,
               rerank: bool | None = None, path_contains: str | None = None,
               since: float | None = None, exact: str | None = None,
               rerank_with: str | None = None) -> list[dict]:
        vec = self.embedder.embed([query])[0]
        filtered = bool(tag or path_contains or since or exact or rerank)
        # over-fetch so fusion and filtering still leave top_k results
        fetch = self.top_k * 4 if (self.hybrid or filtered) else self.top_k
        vhits = self.store.query(vec, fetch)
        fused = self._fuse(vhits, query, fetch)
        if tag:
            t = tag.lower()
            fused = [h for h in fused if t in h["tags"].lower()]
        if path_contains:
            p = path_contains.lower()
            fused = [h for h in fused if p in h["source"].lower()]
        if since:
            fused = [h for h in fused if h.get("mtime", 0.0) >= since]
        if exact:
            e = exact.lower()
            fused = [h for h in fused if e in h["text"].lower()]
        use_rerank = self.rerank if rerank is None else rerank
        if use_rerank:
            provider = rerank_with or self.rerank_provider
            if provider == "local":
                fused = local_rerank(query, fused, self.local_rerank_model)
            elif self.llm_cfg:
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
        pairs = json.loads(resp.choices[0].message.content or "[]")
        scores = {int(idx): float(s) for idx, s in pairs}
        if not scores:
            return hits
        return [h for _, _, h in sorted(
            ((scores.get(i, 0.0), -i, h) for i, h in enumerate(hits)),
            key=lambda t: (-t[0], t[1]))]
    except Exception:
        return hits


VERIFY_PROMPT = (
    "You audit RAG answers for faithfulness. You get a question, an answer, "
    "and numbered source excerpts. Split the answer into its individual "
    "factual claims. For each claim, decide whether the excerpts support it. "
    'Reply with ONLY a JSON array like [{"claim": "...", "status": "supported", '
    '"excerpt": 2}] — status is "supported", "partial" or "unsupported"; '
    '"excerpt" is the best supporting excerpt number, or null when unsupported. '
    "Do not use outside knowledge to judge claims."
)

_STATUS_MARK = {"supported": "✓", "partial": "~", "unsupported": "✗"}


def verify_answer(llm_cfg: dict, question: str, answer_text: str,
                  hits: list[dict]) -> str:
    """Self-proving RAG: check every claim in the answer against the sources.
    Fail-open — if the check itself fails, say so and return the note."""
    if not answer_text.strip():
        return "(nothing to verify)"
    try:
        client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
        excerpts = "\n\n".join(
            f"[excerpt {i + 1} | {h['source']}"
            + (f" > {h['section']}" if h.get("section") else "")
            + f"]\n{h['text']}"
            for i, h in enumerate(hits))
        resp = client.chat.completions.create(
            model=llm_cfg["model"],
            messages=[
                {"role": "system", "content": VERIFY_PROMPT},
                {"role": "user",
                 "content": f"Question: {question}\n\nAnswer:\n{answer_text}"
                            f"\n\nExcerpts:\n{excerpts}"},
            ],
            temperature=0.0,
        )
        claims = json.loads(resp.choices[0].message.content or "[]")
        if not claims:
            return "(verification returned no claims — answer not audited)"
        lines = []
        for c in claims:
            claim = str(c.get("claim", "")).strip()
            status = str(c.get("status", "unsupported")).lower()
            mark = _STATUS_MARK.get(status, "?")
            idx = c.get("excerpt")
            where = f" [excerpt {idx}]" if isinstance(idx, int) and 0 < idx <= len(hits) else ""
            lines.append(f"  {mark} {claim}{where}")
        return ("Claim-by-claim check against the sources "
                f"(✓ supported, ~ partial, ✗ unsupported):\n" + "\n".join(lines))
    except Exception as e:
        return f"(verification unavailable: {type(e).__name__}: {e})"


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
