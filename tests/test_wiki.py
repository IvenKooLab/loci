"""Wiki generation tests: retrieve -> distill (fake LLM) -> write -> index."""
from pathlib import Path

import pytest

import loci.cli as cli_module
import loci.mcp_server as mcp_module
import loci.wiki as wiki_module
from conftest import FakeEmbedder, build_index, make_cfg, write_corpus
from loci.mcp_server import Brain, handle_message
from loci.retriever import Retriever
from loci.store import Store
from loci.wiki import generate_wiki_page

CORPUS = {
    "t.md": "# Turing\nacceleration routes on the 22G card",
    "v.md": "# Vectors\nchromadb stores the embeddings",
}

PAGE_BODY = ("# Turing acceleration\n\n## Overview\n\nThe 22G card runs H3 via "
             "[[W4A8 quantization]].\n\n## Details\n\nSageAttention is not "
             "available on this architecture.")


class FakeLLM:
    """Fake OpenAI client returning a fixed wiki page body."""

    reply = ""

    def __init__(self, **kw):
        outer = self

        class Completions:
            def create(self, **kwargs):
                class Msg:
                    content = outer.reply

                class Choice:
                    message = Msg()

                class Resp:
                    choices = [Choice()]

                return Resp()

        self.chat = type("C", (), {"completions": Completions()})()


def wired(monkeypatch, tmp_path, llm_reply, hybrid=True):
    sources = write_corpus(tmp_path, CORPUS)
    cfg = make_cfg(tmp_path, sources)
    cfg.llm["api_key"] = "k"
    cfg.embed["api_key"] = "k"
    cfg.wiki["path"] = str(tmp_path / "wiki")

    _, store, retriever = build_index(cfg, hybrid=hybrid)   # ingest corpus first
    monkeypatch.setattr(cli_module, "build",
                        lambda c: (FakeEmbedder(), store))
    monkeypatch.setattr(cli_module, "make_retriever",
                        lambda c, e, s: retriever)

    FakeLLM.reply = llm_reply
    monkeypatch.setattr(wiki_module, "OpenAI", FakeLLM)
    return cfg, store, retriever, FakeLLM


def test_generate_writes_page_with_sources_and_indexes(monkeypatch, tmp_path):
    cfg, store, _, _ = wired(monkeypatch, tmp_path, PAGE_BODY)
    r = generate_wiki_page(cfg, "turing acceleration")
    assert r["sources"] >= 2 and r["chunks"] >= 1
    text = Path(r["path"]).read_text(encoding="utf-8")
    assert text.startswith("---\n")              # frontmatter
    assert "tags: [wiki" in text
    assert "## Sources" in text                  # citations appended
    assert "t.md" in text and "v.md" in text     # every source cited
    # the page itself is now part of the index
    assert any("Turing acceleration" in d for d in store.all_chunks()[1])


def test_generate_uses_llm_output_body(monkeypatch, tmp_path):
    cfg, _, _, _ = wired(monkeypatch, tmp_path, PAGE_BODY)
    r = generate_wiki_page(cfg, "turing acceleration")
    text = Path(r["path"]).read_text(encoding="utf-8")
    assert "W4A8 quantization" in text           # LLM body, not template filler
    assert "[[W4A8 quantization]]" in text       # wikilinks preserved


def test_regenerate_overwrites_same_page(monkeypatch, tmp_path):
    cfg, store, retriever, _ = wired(monkeypatch, tmp_path, PAGE_BODY)
    r1 = generate_wiki_page(cfg, "turing acceleration")
    total_after_first = store.count()
    print("\nDBG gen1 total:", total_after_first,
          "| per-source:", {k.rsplit("\\", 1)[-1]: v for k, v in
          __import__("collections").Counter(
              i.rsplit("::", 1)[0] for i in store.all_chunks()[0]).items()})
    r2 = generate_wiki_page(cfg, "turing acceleration")
    print("DBG gen2 total:", store.count(), "| r2 chunks:", r2["chunks"],
          "| per-source:", {k.rsplit("\\", 1)[-1]: v for k, v in
          __import__("collections").Counter(
              i.rsplit("::", 1)[0] for i in store.all_chunks()[0]).items()})
    assert r1["path"] == r2["path"]              # same slug = same page
    assert store.count() == total_after_first    # replaced, not duplicated


def test_empty_index_raises_lookup_error(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path, [{"path": str(tmp_path / "empty")}])   # no corpus
    cfg.llm["api_key"] = "k"
    cfg.embed["api_key"] = "k"
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr(cli_module, "build",
                        lambda c: (FakeEmbedder(), Store(str(tmp_path / "chroma"))))
    with pytest.raises(LookupError):
        generate_wiki_page(cfg, "anything at all")


def test_brain_wiki_tool_returns_summary(monkeypatch, tmp_path):
    cfg, store, retriever, _ = wired(monkeypatch, tmp_path, PAGE_BODY)
    monkeypatch.setattr(mcp_module.config, "load",
                        lambda path="config.toml": cfg)
    b = Brain()
    r = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "brain_wiki",
                                   "arguments": {"topic": "turing acceleration"}}}, b)
    text = r["result"]["content"][0]["text"]
    assert "wiki page written" in text and "searchable" in text
