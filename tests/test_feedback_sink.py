"""`loci feedback bad` is documented to sink the rated chunks in later
retrieval. It did not reorder anything: the penalty only inflated each
hit's `distance`, and in hybrid mode — the default — rank comes from RRF
scores, not distance. A bad-rated chunk kept its place at the top with a
worse-looking score. (The existing test passed on an `or`: "not first OR
distance larger".)

A bad rating now demotes its chunk by one result page (top_k positions)
per rating, after any reranking, in both retrieval modes.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import FakeEmbedder, build_index, make_cfg, write_corpus
from loci.retriever import Retriever

QUERY = "turing acceleration"
# the shortest note is the closest match for a two-token query: cosine 1.0
CORPUS = {"top.md": f"# Top\n\n{QUERY}"}
CORPUS.update({f"n{i}.md": f"# Note {i}\n\n{QUERY} extra{i} padding words here"
               for i in range(7)})


def _rate_bad(store_path, chunk_id, times=1):
    fb = Path(store_path) / "feedback.jsonl"
    fb.parent.mkdir(parents=True, exist_ok=True)
    with fb.open("a", encoding="utf-8") as f:
        for _ in range(times):
            f.write(json.dumps({"chunk_id": chunk_id, "query": "q", "verdict": "bad", "ts": 0}) + "\n")
    return str(fb)


def _rank(hits, chunk_id):
    return [h["id"] for h in hits].index(chunk_id)


def _index_at(root, hybrid):
    root.mkdir()                       # write_corpus creates <root>/notes, not <root>
    cfg = make_cfg(root, write_corpus(root, CORPUS))
    return cfg, build_index(cfg, hybrid=hybrid)


def test_control_the_best_match_ranks_first_in_both_modes(tmp_path):
    for hybrid in (True, False):
        _, (_, _, retriever) = _index_at(tmp_path / f"c{hybrid}", hybrid)
        hits = retriever.search(QUERY)
        assert len(hits) == 5 and hits[0]["source"].endswith("top.md"), hybrid


def test_one_bad_rating_moves_the_chunk_down_one_page(tmp_path):
    for hybrid in (True, False):
        cfg, (_, store, retriever) = _index_at(tmp_path / f"m{hybrid}", hybrid)
        top = retriever.search(QUERY)[0]["id"]
        others = [h["id"] for h in retriever.search(QUERY, k=20)[1:]]

        rated = Retriever(FakeEmbedder(), store, cfg.top_k["search"], hybrid=hybrid,
                          rrf_k=cfg.retrieval["rrf_k"],
                          feedback_path=_rate_bad(cfg.store["path"], top))
        hits = rated.search(QUERY)

        assert top not in [h["id"] for h in hits], f"bad-rated chunk still in the top {len(hits)} (hybrid={hybrid})"
        # the chunks nobody rated keep their relative order
        assert [h["id"] for h in hits] == others[:len(hits)]


def test_two_bad_ratings_move_it_down_two_pages(tmp_path):
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, CORPUS))
    _, store, retriever = build_index(cfg, hybrid=True)
    top = retriever.search(QUERY)[0]["id"]

    rated = Retriever(FakeEmbedder(), store, cfg.top_k["search"], hybrid=True,
                      rrf_k=cfg.retrieval["rrf_k"],
                      feedback_path=_rate_bad(cfg.store["path"], top, times=2))
    hits = rated.search(QUERY, k=20)
    assert len(hits) == 8 and hits[-1]["id"] == top          # last of eight


def test_a_good_rating_demotes_nothing(tmp_path):
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, CORPUS))
    _, store, retriever = build_index(cfg, hybrid=True)
    top = retriever.search(QUERY)[0]["id"]
    fb = Path(cfg.store["path"]) / "feedback.jsonl"
    fb.parent.mkdir(parents=True, exist_ok=True)
    fb.write_text(json.dumps({"chunk_id": top, "query": "q", "verdict": "good", "ts": 0}) + "\n",
                  encoding="utf-8")

    rated = Retriever(FakeEmbedder(), store, cfg.top_k["search"], hybrid=True,
                      rrf_k=cfg.retrieval["rrf_k"], feedback_path=str(fb))
    assert rated.search(QUERY)[0]["id"] == top


def test_the_demotion_survives_reranking(tmp_path, monkeypatch):
    """A reranker scores relevance only; the user's rating is the last word."""
    import loci.retriever as r
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, CORPUS))
    _, store, retriever = build_index(cfg, hybrid=True)
    top = retriever.search(QUERY)[0]["id"]

    def rerank_puts_it_back(llm_cfg, query, hits):      # a reranker that favours the bad chunk
        return sorted(hits, key=lambda h: h["id"] != top)

    monkeypatch.setattr(r, "rerank_hits", rerank_puts_it_back)
    rated = Retriever(FakeEmbedder(), store, cfg.top_k["search"], hybrid=True,
                      rrf_k=cfg.retrieval["rrf_k"], rerank=True, llm_cfg={"api_key": "k"},
                      feedback_path=_rate_bad(cfg.store["path"], top))
    assert top not in [h["id"] for h in rated.search(QUERY)]
