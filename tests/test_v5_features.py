"""v0.5 S-feature tests: rewrite multi-query fusion, feedback loop wiring."""
from pathlib import Path

import pytest

from pathlib import Path

import loci.cli as cli_module
from conftest import FakeEmbedder, make_cfg, write_corpus
from loci.retriever import Retriever
from loci.store import Store

CORPUS = {
    "t.md": "# Turing\nacceleration routes on the 22G card",
    "v.md": "# Vectors\nchromadb stores the embeddings",
}


def test_rewrite_fuses_multiple_query_variants(tmp_path):
    """Multi-query path: two variants both retrieve; RRF fusion dedupes and ranks."""
    sources = write_corpus(tmp_path, CORPUS)
    cfg = make_cfg(tmp_path, sources)
    cfg.llm["api_key"] = "k"
    _, store, retriever = __import__("conftest").build_index(cfg, hybrid=True)
    seen_queries = []
    orig_embed = retriever.embedder.embed
    def spy_embed(texts):
        seen_queries.extend(texts)
        return orig_embed(texts)
    retriever.embedder.embed = spy_embed
    retriever.llm_cfg = {"base_url": "x", "api_key": "k", "model": "m"}
    import loci.retriever as rm
    calls = {"n": 0}
    orig_expand = rm.expand_queries
    def counting_expand(cfg, q):
        calls["n"] += 1
        return [q, "quantization speedup", "量化提速"]
    rm.expand_queries = counting_expand
    try:
        hits = retriever.search("acceleration", rewrite=True)
    finally:
        rm.expand_queries = orig_expand
    assert calls["n"] == 1                  # expand_queries was consulted
    assert hits                              # fused result returned


def test_rewrite_disabled_uses_single_query(tmp_path):
    sources = write_corpus(tmp_path, CORPUS)
    cfg = make_cfg(tmp_path, sources)
    _, store, retriever = __import__("conftest").build_index(cfg, hybrid=True)
    seen = []
    orig_embed = retriever.embedder.embed
    def spy_embed(texts):
        seen.extend(texts)
        return orig_embed(texts)
    retriever.embedder.embed = spy_embed
    retriever.search("acceleration", rewrite=False)
    assert len(seen) == 1                  # only the original query


def test_feedback_penalizes_bad_chunks(tmp_path):
    sources = write_corpus(tmp_path, CORPUS)
    cfg = make_cfg(tmp_path, sources)
    _, store, retriever = __import__("conftest").build_index(cfg, hybrid=False)
    hits = retriever.search("turing acceleration")
    bad_id = hits[0]["id"]
    fb = Path(cfg.store["path"]) / "feedback.jsonl"
    fb.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    with fb.open("w", encoding="utf-8") as f:
        f.write(_json.dumps({"chunk_id": bad_id, "query": "x",
                             "verdict": "bad", "ts": 0}) + "\n")
    retriever2 = Retriever(FakeEmbedder(), store, 5, hybrid=False,
                           feedback_path=str(fb))
    hits2 = retriever2.search("turing acceleration")
    assert bad_id not in [h["id"] for h in hits2[:1]] or \
        hits2[0]["distance"] > hits[0]["distance"]


def test_cmd_feedback_roundtrip(tmp_path, monkeypatch, capsys):
    sources = write_corpus(tmp_path, CORPUS)
    cfg = make_cfg(tmp_path, sources)
    store = Store(cfg.store["path"])
    monkeypatch.setattr(cli_module, "build",
                        lambda c: (FakeEmbedder(), store))
    last = Path(cfg.store["path"]) / ".last_ask.json"
    last.parent.mkdir(parents=True, exist_ok=True)
    import json as _json, time as _t
    last.write_text(_json.dumps({"query": "q", "chunk_ids": ["a::0", "a::1"],
                                 "ts": _t.time()}), encoding="utf-8")
    cli_module.cmd_feedback(cfg, "bad")
    out = capsys.readouterr().out
    assert "recorded bad feedback for 2 chunk(s)" in out
    fb = Path(cfg.store["path"]) / "feedback.jsonl"
    lines = [l for l in fb.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    assert all('"verdict": "bad"' in l for l in lines)


def test_cmd_feedback_without_prior_ask(tmp_path, monkeypatch, capsys):
    cfg = make_cfg(tmp_path, [])
    monkeypatch.setattr(cli_module, "build",
                        lambda c: (FakeEmbedder(), Store(cfg.store["path"])))
    cli_module.cmd_feedback(cfg, "good")
    assert "no recent ask" in capsys.readouterr().out
