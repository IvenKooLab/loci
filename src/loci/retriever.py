"""Retrieval: vector search fused with BM25 via Reciprocal Rank Fusion,
LLM reranking and answer verification, and grounded answer synthesis."""
from __future__ import annotations

import json
import re
from pathlib import Path

from openai import OpenAI

from loci.bm25_cache import BM25Cache
from loci.reranker import local_rerank

SYSTEM_PROMPT = (
    "You are a Q&A assistant over the user's personal knowledge base. "
    "Answer only from the provided excerpts; if they don't contain the answer, "
    "say so plainly — do not invent. End your reply with a list of citations "
    "in the form [source: file path > section]."
)


# Identifiers are the queries semantic ranking serves worst: `user_id`,
# `user-id` and `user id` carry the same words but mean different things, and
# an embedding sees all three as "about users". A literal match is the honest
# signal, so an identifier-shaped query gets one — additive only, it promotes
# chunks that contain the exact string and never removes a result.
_IDENTIFIER_QUERY = re.compile(
    r"[A-Za-z0-9]+(?:[-_.:/]{1,2}[A-Za-z0-9]+)+"      # user_id, api/v2, a.b.c, ns::f
    r"|[A-Za-z]*\d[A-Za-z0-9]*")                      # SHT45, v2, x64


def identifier_terms(query: str) -> list[str]:
    """Identifier-shaped literals in a query, lowercased and de-duplicated.

    Plain words, single letters and pure numbers are excluded: they match too
    much text to be a precise signal, and boosting them would just re-rank
    common words.
    """
    terms: list[str] = []
    for match in _IDENTIFIER_QUERY.finditer(query):
        token = match.group(0).lower().strip("-_.:/")
        if len(token) < 3 or token.isdigit() or token in terms:
            continue
        # a bare word with a trailing digit (`sht45`) is worth matching; a
        # single letter plus digit (`v2`) is too common to be a signal
        if len(token) <= 2:
            continue
        terms.append(token)
    return terms


class Retriever:
    def __init__(self, embedder, store, top_k: int,
                 hybrid: bool = True, rrf_k: int = 60,
                 rerank: bool = False, llm_cfg: dict | None = None,
                 rerank_provider: str = "llm",
                 local_rerank_model: str = "BAAI/bge-reranker-base",
                 feedback_path: str | None = None,
                 bm25_tokenizer: str = "default"):
        self.embedder, self.store, self.top_k = embedder, store, top_k
        self.hybrid, self.rrf_k = hybrid, rrf_k
        self.rerank, self.llm_cfg = rerank, llm_cfg
        self.rerank_provider = rerank_provider
        self.local_rerank_model = local_rerank_model
        self.bm25_tokenizer = bm25_tokenizer
        self._bm25_cache = BM25Cache()
        self._penalties: dict[str, float] = {}
        if feedback_path and Path(feedback_path).exists():
            import json as _json
            for line in Path(feedback_path).read_text(encoding="utf-8").splitlines():
                try:
                    rec = _json.loads(line)
                    if rec.get("verdict") == "bad":
                        cid = rec["chunk_id"]
                        self._penalties[cid] = self._penalties.get(cid, 0.0) + 0.5
                except Exception:
                    pass

    def _apply_feedback(self, hits):
        if not self._penalties:
            return hits
        for h in hits:
            p = self._penalties.get(h["id"], 0.0)
            if p:
                h["distance"] = (h.get("distance") or 0.5) + p * 0.3
        return hits

    def search(self, query: str, tag: str | None = None,
               rerank: bool | None = None, path_contains: str | None = None,
               since: float | None = None, exact: str | None = None,
               rerank_with: str | None = None, k: int | None = None,
               rewrite: bool | None = None) -> list[dict]:
        limit = max(k if k is not None else self.top_k, 0)
        filtered = bool(tag or path_contains or since or exact or rerank)
        # over-fetch so fusion and filtering still leave `limit` results
        fetch = max(limit * 4, 1) if (self.hybrid or filtered) else max(limit, 1)
        use_rw = False if rewrite is None else rewrite   # off unless asked
        queries = [query]
        if use_rw and self.llm_cfg:
            queries = expand_queries(self.llm_cfg, query) or [query]
        # multi-query: retrieve per variant, RRF-fuse across all result lists
        all_ranks: list[list[dict]] = []
        for q in queries:
            vec = self.embedder.embed([q])[0]
            fh = max(fetch, 1) if len(queries) > 1 else fetch
            vh = self.store.query(vec, fh)
            all_ranks.append(self._fuse(vh, q, fh))
        fused = self._rrf_merge(all_ranks)
        if tag:
            t = tag.lower()
            # exact tag match against the comma-joined list — substring would
            # let `--tag rag` hit "storage"
            fused = [h for h in fused
                     if t in [x.strip().lower() for x in h["tags"].split(",") if x.strip()]]
        if path_contains:
            # normalize separators so `--in docs/en` works on Windows paths too
            p = path_contains.lower().replace("\\", "/")
            fused = [h for h in fused if p in h["source"].lower().replace("\\", "/")]
        if since:
            fused = [h for h in fused if h.get("mtime", 0.0) >= since]
        if exact:
            e = exact.lower()
            fused = [h for h in fused if e in h["text"].lower()]
        fused = self._apply_feedback(fused)   # bad-rated chunks sink
        use_rerank = self.rerank if rerank is None else rerank
        if use_rerank:
            provider = rerank_with or self.rerank_provider
            if provider == "local":
                fused = local_rerank(query, fused, self.local_rerank_model)
            elif self.llm_cfg:
                fused = rerank_hits(self.llm_cfg, query, fused)
        return fused[:limit]

    @staticmethod
    def _rrf_merge(ranked_lists: list[list[dict]], rrf_k: int = 60) -> list[dict]:
        scores: dict[str, float] = {}
        by_id: dict[str, dict] = {}
        for hits in ranked_lists:
            for r, h in enumerate(hits):
                scores[h['id']] = scores.get(h['id'], 0.0) + 1.0 / (rrf_k + r + 1)
                by_id[h['id']] = h
        ordered = sorted(scores.items(), key=lambda kv: -kv[1])
        return [by_id[cid] for cid, _ in ordered]

    def _fuse(self, vhits: list[dict], query: str, fetch: int) -> list[dict]:
        if not self.hybrid:
            return vhits
        ids, docs = self.store.all_chunks()
        if not ids:
            return vhits
        # building BM25 is O(corpus) — 290 ms at 10k chunks — so hold it while
        # the store is unchanged instead of paying that on every query
        ranked = self._bm25_cache.get(self.store.path, ids, docs,
                                      self.bm25_tokenizer).score(query)[:fetch]
        scores: dict[str, float] = {}
        for r, h in enumerate(vhits):
            scores[h["id"]] = scores.get(h["id"], 0.0) + 1.0 / (self.rrf_k + r + 1)
        for r, (cid, _) in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (self.rrf_k + r + 1)
        by_id = {h["id"]: h for h in vhits}
        # Identifier-shaped queries get an exact-literal channel (Dan Kornas'
        # point: a specific symbol should not have to win a semantic ranking).
        # The corpus texts are already in hand from the cache path, so this is
        # one substring scan, and only for queries that contain an identifier.
        # Additive: it promotes literal matches, never drops a result.
        terms = identifier_terms(query)
        if terms:
            for cid, doc in zip(ids, docs):
                lowered = doc.lower()
                hits = sum(1 for term in terms if term in lowered)
                if hits:
                    # an RRF contribution is ~1/(60+r) ≈ 0.016, so a whole
                    # point per matched term puts literal hits decisively above
                    # semantic-only ones while preserving their order among
                    # themselves
                    scores[cid] = scores.get(cid, 0.0) + float(hits)

        ordered = sorted(scores.items(), key=lambda kv: -kv[1])[: self.top_k * 4]
        missing = [cid for cid, _ in ordered if cid not in by_id]
        if missing:
            by_id.update({h["id"]: h for h in self.store.get_many(missing)})
        return [by_id[cid] for cid, _ in ordered if cid in by_id]

QUERY_REWRITE_PROMPT = (
    "Rewrite this search query for a personal knowledge base to improve retrieval. "
    "Generate 2 alternative versions: 1) a keyword-only version (drop stop words), "
    "2) a translation in the other language (Chinese→English or English→Chinese). "
    'Reply with ONLY a JSON array of strings, e.g. ["keyword version", "翻译版本"].'
)


def expand_queries(llm_cfg: dict, query: str) -> list[str]:
    """LLM-generated query variants for multi-query retrieval. Fail-open."""
    try:
        client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
        resp = client.chat.completions.create(
            model=llm_cfg["model"],
            messages=[
                {"role": "system", "content": QUERY_REWRITE_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
        )
        import json
        variants = json.loads(resp.choices[0].message.content or "[]")
        valid = [v.strip() for v in variants if isinstance(v, str) and v.strip()]
        return [query] + valid if valid else [query]
    except Exception:
        return [query]


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
    "and numbered source excerpts, each labelled with the file it came from.\n\n"
    "Split the answer into its individual factual claims. For each claim, find "
    "every excerpt that supports it, then decide:\n"
    '  "supported"   — the excerpts state it outright\n'
    '  "partial"     — they support part of it, or support it only through a '
    "step they do not state\n"
    '  "unsupported" — nothing in the excerpts backs it\n\n'
    "CROSS-FILE CHECK — required whenever a claim rests on excerpts from more "
    "than one file. Two accurate citations can still be joined into a wrong "
    "conclusion, so verify the join itself: are the excerpts about the same "
    "entity, version, time period and scope? Does the combination license the "
    "claim, or does it need an assumption the sources never state? Report "
    '\"cross_file\":\n'
    '  "n/a"      — the claim rests on a single excerpt\n'
    '  "ok"       — the multi-source join is licensed by what the excerpts say\n'
    '  "unstated" — each citation is accurate, but the inference joining them '
    'is not stated in the sources; name the missing step in \"reason\"\n\n'
    "Reply with ONLY a JSON array like "
    '[{"claim": "...", "status": "supported", "excerpts": [1, 3], '
    '"cross_file": "ok", "reason": ""}] — "excerpts" lists every excerpt the '
    "claim relies on; \"reason\" is a short note, used when status is not "
    "\"supported\" or cross_file is \"unstated\". "
    "Do not use outside knowledge to judge claims."
)

_STATUS_MARK = {"supported": "✓", "partial": "~", "unsupported": "✗"}


def _excerpt_refs(claim: dict, n_hits: int) -> list[int]:
    """Excerpt numbers a claim cites, from `excerpts` (list) or `excerpt` (int)."""
    raw = claim.get("excerpts")
    if raw is None:
        raw = claim.get("excerpt")
    if isinstance(raw, (int, float)):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [int(i) for i in raw
            if isinstance(i, (int, float)) and 0 < int(i) <= n_hits]


def format_verification(claims: list, hits: list[dict]) -> str:
    """Render the verification report. Pure — no LLM, so it is testable.

    A multi-file answer is called out in the header, and a claim whose support
    needs a cross-file inference the sources do not license is marked with the
    missing step, rather than getting a clean ✓.
    """
    files = {h["source"] for h in hits}
    header = ("Claim-by-claim check against the sources "
              "(✓ supported, ~ partial, ✗ unsupported):")
    if len(files) > 1:
        header = (f"Claim-by-claim check across {len(files)} files "
                  f"({len(hits)} excerpts; ✓ supported, ~ partial, "
                  "✗ unsupported, ⚠ unlicensed cross-file join):")
    lines = []
    for c in claims:
        claim = str(c.get("claim", "")).strip()
        status = str(c.get("status", "unsupported")).lower()
        mark = _STATUS_MARK.get(status, "?")
        refs = _excerpt_refs(c, len(hits))
        # singular for one source of support, plural when the claim needs a
        # join — the shape of the citation is itself information
        if len(refs) == 1:
            where = f" [excerpt {refs[0]}]"
        elif refs:
            where = f" [excerpts {', '.join(str(r) for r in refs)}]"
        else:
            where = ""
        line = f"  {mark} {claim}{where}"
        cross = str(c.get("cross_file", "")).lower()
        reason = str(c.get("reason", "")).strip()
        if cross == "unstated":
            # the exact failure mode the review thread named: both citations
            # check out, the conclusion does not follow from them
            line += "  ⚠ cross-file inference not in the sources"
            if reason:
                line += f": {reason}"
        elif cross == "ok" and len(refs) > 1:
            line += "  (cross-file join checked)"
        lines.append(line)
    return header + "\n" + "\n".join(lines)


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
        return format_verification(claims, hits)
    except Exception as e:
        return f"(verification unavailable: {type(e).__name__}: {e})"


def answer(llm_cfg: dict, question: str, hits: list[dict],
           history: list[dict] | None = None) -> str:
    def _warn(hit: dict) -> str:
        # a superseded note is history, not current practice: say so in the
        # context, or the model will quote last quarter's decision as policy
        if not hit.get("superseded_by"):
            return ""
        when = f" (effective {hit['effective']})" if hit.get("effective") else ""
        return (f"\n[SUPERSEDED by {hit['superseded_by']}{when} — historical, "
                "not current practice]")

    context = "\n\n---\n\n".join(
        f"[chunk {i + 1} | source: {h['source']}"
        + (f" | section: {h['section']}" if h.get("section") else "")
        + f"]{_warn(h)}\n{h['text']}"
        for i, h in enumerate(hits))
    client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user",
                     "content": f"Excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"})
    resp = client.chat.completions.create(
        model=llm_cfg["model"], messages=messages, temperature=0.3)
    return resp.choices[0].message.content or ""
