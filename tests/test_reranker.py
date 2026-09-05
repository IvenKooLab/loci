import second_brain.retriever as retriever_module
from second_brain.reranker import local_rerank, order_by_scores

HITS = [{"id": "fused-1st", "text": "weak", "source": "a.md", "section": "",
         "tags": "", "links": "", "chunk": 0, "mtime": 0.0, "distance": None},
        {"id": "fused-2nd", "text": "strong match for the query terms",
         "source": "b.md", "section": "", "tags": "", "links": "", "chunk": 0,
         "mtime": 0.0, "distance": None}]


def test_order_by_scores_descending_stable():
    hits = list(HITS)
    out = order_by_scores(hits, [0.1, 9.9])
    assert [h["id"] for h in out] == ["fused-2nd", "fused-1st"]


def test_order_by_scores_ties_keep_fused_rank():
    hits = list(HITS)
    out = order_by_scores(hits, [5.0, 5.0])
    assert [h["id"] for h in out] == ["fused-1st", "fused-2nd"]


def test_local_rerank_uses_crossencoder_scores(monkeypatch):
    class FakeCross:
        def predict(self, pairs):
            assert pairs[0][0] == "the query"
            return [0.0, 8.0]

    import second_brain.reranker as rr
    monkeypatch.setattr(rr, "_get_model", lambda name: FakeCross())
    out = local_rerank("the query", HITS, "fake-model")
    assert [h["id"] for h in out] == ["fused-2nd", "fused-1st"]


def test_local_rerank_fail_open_on_scoring_error(monkeypatch):
    class Boom:
        def predict(self, pairs):
            raise RuntimeError("cuda died")

    import second_brain.reranker as rr
    monkeypatch.setattr(rr, "_get_model", lambda name: Boom())
    out = local_rerank("q", HITS, "fake-model")
    assert [h["id"] for h in out] == ["fused-1st", "fused-2nd"]


def test_local_rerank_fail_open_when_model_missing(monkeypatch):
    import second_brain.reranker as rr
    monkeypatch.setattr(rr, "_get_model", lambda name: None)  # e.g. no extra installed
    out = local_rerank("q", HITS, "fake-model")
    assert [h["id"] for h in out] == ["fused-1st", "fused-2nd"]


def test_local_rerank_single_hit_short_circuits(monkeypatch):
    import second_brain.reranker as rr
    monkeypatch.setattr(rr, "_get_model",
                        lambda name: (_ for _ in ()).throw(AssertionError("no call")))
    assert local_rerank("q", HITS[:1], "m") == HITS[:1]


def test_retriever_dispatches_local_provider(monkeypatch, tmp_path):
    """--rerank local must hit the cross-encoder path, not the LLM one."""
    import second_brain.retriever as rm
    from conftest import build_index, make_cfg, write_corpus

    sources = write_corpus(tmp_path, {"a.md": "# A\nvector search notes here",
                                      "b.md": "# B\nunrelated grocery list"})
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    retriever.top_k = 2

    calls = {}
    monkeypatch.setattr(rm, "local_rerank",
                        lambda q, hits, model: calls.update(provider="local",
                                                            model=model) or hits)

    def boom(*a, **k):
        raise AssertionError("llm reranker must not run for provider=local")

    monkeypatch.setattr(rm, "rerank_hits", boom)
    out = retriever.search("vector search", rerank=True, rerank_with="local")
    assert calls == {"provider": "local", "model": "BAAI/bge-reranker-base"}
    assert out  # results still returned


def test_retriever_default_provider_is_llm(tmp_path):
    from conftest import build_index, make_cfg, write_corpus
    sources = write_corpus(tmp_path, {"a.md": "# A\nvector search notes here"})
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    assert retriever.rerank_provider == "llm"
    assert retriever.local_rerank_model == "BAAI/bge-reranker-base"
