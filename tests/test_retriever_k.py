"""Two retrieval bugs found while sweeping the sweep: an identifier-shaped
query with an explicit k used to be truncated to top_k*4 by the literal-
match channel, and expand_queries turned a bare-string LLM reply into
junk single-character variants."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import FakeEmbedder, make_cfg, write_corpus
from loci import cli
from loci.retriever import expand_queries
from loci.store import Store


def _retriever(tmp_path, n_docs=30):
    cfg = make_cfg(tmp_path, write_corpus(
        tmp_path, {f"doc{i}.md": f"# D{i}\nuser_id mention {i} " * 10
                   for i in range(n_docs)}))
    embedder = FakeEmbedder()
    store = Store(cfg.store["path"])
    cli.build = lambda c: (embedder, store)
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        cli.cmd_ingest(cfg)
    r = cli.make_retriever(cfg, embedder, store)
    r.top_k = 5
    return r


def test_identifier_query_honours_large_k(tmp_path):
    r = _retriever(tmp_path)
    assert len(r.search("user_id", k=50)) == 30      # all 30 docs, not 20


def test_small_k_still_works(tmp_path):
    r = _retriever(tmp_path)
    assert len(r.search("user_id", k=5)) == 5


def test_expand_queries_ignores_non_list_reply(tmp_path, monkeypatch):
    cfg = {"base_url": "x", "api_key": "k", "model": "m"}

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**k):
                    class R:
                        choices = [type("C", (), {"message": type(
                            "M", (), {"content": '"just a string"'})()})()]
                    return R()
    monkeypatch.setattr("loci.retriever.OpenAI", lambda **k: FakeClient())
    out = expand_queries(cfg, "sensor")
    assert out == ["sensor"]                          # no junk 1-char variants
