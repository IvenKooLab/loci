"""Local cross-encoder reranking via sentence-transformers (optional extra:
`pip install 'second-brain-rag[rerank]'`). Recommended model: BAAI/bge-reranker-base
(bilingual zh/en). Downloads from HuggingFace on first use — set HF_ENDPOINT
if needed."""
from __future__ import annotations

import sys

_model = None
_loaded_name = ""


def _get_model(model_name: str):
    global _model, _loaded_name
    if _model is None or _loaded_name != model_name:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            print("[rerank] sentence-transformers not installed — local rerank "
                  "skipped (pip install 'second-brain-rag[rerank]')", file=sys.stderr)
            return None
        try:
            print(f"[rerank] loading local cross-encoder {model_name} "
                  "(first run downloads it from HuggingFace)", file=sys.stderr)
            _model = CrossEncoder(model_name)
            _loaded_name = model_name
        except Exception as e:
            print(f"[rerank] model load failed, local rerank skipped: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            return None
    return _model


def order_by_scores(hits: list[dict], scores) -> list[dict]:
    """Sort hits by descending score; stable on ties (original fused rank wins)."""
    ranked = sorted(zip(hits, scores), key=lambda hs: -float(hs[1]))
    return [h for h, _ in ranked]


def local_rerank(query: str, hits: list[dict], model_name: str,
                   text_limit: int = 512) -> list[dict]:
    """Cross-encoder rerank. Fail-open: any problem returns the fused order."""
    if len(hits) < 2:
        return hits
    model = _get_model(model_name)
    if model is None:
        return hits
    try:
        pairs = [(query, h["text"][:text_limit]) for h in hits]
        scores = model.predict(pairs)
        return order_by_scores(hits, scores)
    except Exception as e:
        print(f"[rerank] scoring failed, keeping fused order: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return hits
