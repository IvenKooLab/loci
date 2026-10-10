"""Cross-session memory tests: write, recall, forget, and multi-process sharing."""
from pathlib import Path

import pytest

import loci.cli as cli_module
import loci.mcp_server as mcp_module
from conftest import FakeEmbedder, build_index, make_cfg, write_corpus
from loci.memories import (find_memories, forget_memory, index_memory_file,
                           write_memory)
from loci.mcp_server import Brain, handle_message
from loci.store import Store


def test_write_memory_creates_frontmatter_note(tmp_path):
    p = write_memory(str(tmp_path), "deploy uses blue-green", title="deploy strategy",
                     tags=["ops"])
    text = Path(p).read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "memory" in text and "ops" in text
    assert "deploy uses blue-green" in text


def test_same_second_writes_get_unique_names(tmp_path):
    a = write_memory(str(tmp_path), "first memory", title="same")
    b = write_memory(str(tmp_path), "second memory", title="same")
    assert a != b and Path(a).exists() and Path(b).exists()


def test_find_and_forget_move_to_trash(tmp_path):
    write_memory(str(tmp_path), "# note about kubernetes ingress")
    write_memory(str(tmp_path), "# note about gardening")
    hits = find_memories(str(tmp_path), "kubernetes")
    assert len(hits) == 1 and "kubernetes" in hits[0].name
    original = hits[0]
    moved = forget_memory(str(tmp_path), "kubernetes")
    assert moved and not Path(original).exists()            # original gone
    assert Path(moved[0]).exists()                          # recoverable copy in .trash
    assert Path(moved[0]).parent.name == ".trash"
    assert find_memories(str(tmp_path), "kubernetes") == []


def test_index_memory_file_makes_it_searchable(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, [])
    p = write_memory(str(tmp_path), "the walrus deployment strategy", title="walrus")
    store = Store(str(tmp_path / "chroma"))
    monkeypatch.setattr(cli_module, "build", lambda c: (FakeEmbedder(), store))
    n = index_memory_file(cfg, p)
    assert n >= 1
    assert any("walrus" in d for d in store.all_chunks()[1])


def brain_with_tmp_memories(monkeypatch, tmp_path, indexed=True):
    """Brain wired to a tmp memories dir; pipeline injected per `indexed`."""
    mem = tmp_path / "mem"
    patch = {"memories": {"path": str(mem)}}

    class FakeCfg:
        llm = {"base_url": "x", "api_key": "k", "model": "m"}
        embed = {"base_url": "x", "api_key": "k", "model": "m"}
        sources = []
        chunk = {"size": 800, "overlap": 100}
        top_k = {"search": 5}
        retrieval = {"hybrid": False}
        watch = {}
        memories = patch["memories"]
        store = {"path": str(tmp_path / "chroma")}

        def validate(self):
            pass

    if indexed:
        store = Store(str(tmp_path / "chroma"))
        retriever_hits = store
    monkeypatch.setattr(mcp_module.config, "load",
                        lambda path="config.toml": FakeCfg())
    return FakeCfg(), mem


def test_mcp_brain_remember_roundtrip_unconfigured(monkeypatch, tmp_path):
    """Even with no keys, the WRITE must succeed (file persists for later ingest)."""
    b = Brain()
    monkeypatch.setattr(mcp_module.config, "load",
                        lambda path="config.toml": type(
                            "C", (), {"memories": {"path": str(tmp_path / "mem")},
                                      "llm": {"api_key": ""}, "embed": {"api_key": ""},
                                      "sources": [],
                                      "validate": lambda self: (_ for _ in ()).throw(
                                          SystemExit("Missing configuration"))})())
    b = Brain()
    out = b.remember("remember the milk")
    assert "stored" in out and "not indexed" in out
    files = list((tmp_path / "mem").glob("*.md"))
    assert len(files) == 1 and "milk" in files[0].read_text(encoding="utf-8")


def test_mcp_brain_remember_roundtrip_indexed(monkeypatch, tmp_path):
    """With a working pipeline: remember -> recall via search."""
    from conftest import FakeEmbedder
    from loci.retriever import Retriever

    class FakeCfg:
        llm = {"base_url": "x", "api_key": "k", "model": "m"}
        embed = {"base_url": "x", "api_key": "k", "model": "m"}
        sources = []
        chunk = {"size": 800, "overlap": 100}
        top_k = {"search": 5}
        retrieval = {"hybrid": False, "rrf_k": 60, "rerank": False}
        watch = {}
        memories = {"path": str(tmp_path / "mem")}
        store = {"path": str(tmp_path / "chroma")}

        def validate(self):
            pass

    monkeypatch.setattr(mcp_module.config, "load", lambda path="config.toml": FakeCfg())
    store = Store(str(tmp_path / "chroma"))
    embedder = FakeEmbedder()
    retriever = Retriever(embedder, store, 5, hybrid=False)
    monkeypatch.setattr(cli_module, "build", lambda cfg: (embedder, store))
    monkeypatch.setattr(cli_module, "make_retriever",
                        lambda cfg, e, s: retriever)

    b = Brain()
    out = b.remember("the staging password rotation happens on Mondays",
                     title="password rotation")
    assert "remembered" in out and "searchable now" in out
    # recall in the SAME process
    answer = b.search("password rotation monday")
    assert "rotation" in answer.lower()
    # and it landed on disk as a markdown note too
    notes = list((tmp_path / "mem").glob("*rotation*.md"))
    assert notes and "Mondays" in notes[0].read_text(encoding="utf-8")
