import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loci import chunker, config  # noqa: E402
from loci.bm25 import tokenize  # noqa: E402
from loci.embedder import Embedder  # noqa: E402
from loci.retriever import Retriever  # noqa: E402
from loci.store import Store  # noqa: E402


class FakeEmbedder(Embedder):
    """Deterministic offline embeddings: token-hash bag of words, L2-normalized.

    Shared tokens push cosine similarity up, which is all the ranking sanity
    tests need — no network, no model, stable across machines."""

    def __init__(self, dim: int = 128):
        import hashlib
        self._hashlib = hashlib
        self.dim = dim
        self.model = "fake"
        self.base_url = "offline"
        self.api_key = "offline"

    def embed(self, texts, batch: int = 16):
        return [self._one(t) for t in texts]

    def _one(self, text: str):
        vec = [0.0] * self.dim
        for tok in set(tokenize(text)):
            h = int(self._hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


def make_cfg(tmp_path, sources):
    cfg = config.Config()
    for section, values in config.DEFAULTS.items():
        getattr(cfg, section).update(values)
    cfg.sources = sources
    cfg.store["path"] = str(tmp_path / "chroma")
    return cfg


def write_corpus(tmp_path, files: dict[str, str]) -> list[dict]:
    """Write {name: content} files under tmp_path/notes and return sources config."""
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    for name, content in files.items():
        path = notes / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return [{"path": str(notes)}]


def build_index(cfg, hybrid: bool = True):
    """Ingest the configured sources offline; returns (embedder, store, retriever)."""
    from loci import loaders
    store = Store(cfg.store["path"])
    embedder = FakeEmbedder()
    retriever = Retriever(embedder, store, cfg.top_k["search"],
                          hybrid=hybrid, rrf_k=cfg.retrieval["rrf_k"])
    docs = loaders.scan_sources(cfg.sources)
    for doc in docs:
        size, overlap = chunker.params_for(doc, cfg.chunk)
        chunks = chunker.split_markdown(doc["content"], size, overlap)
        if chunks:
            vectors = embedder.embed([c["text"] for c in chunks])
            store.upsert_chunks(chunks, vectors, doc["path"], doc["hash"],
                                doc["tags"], doc["links"], doc["mtime"])
    return embedder, store, retriever


def patch_brain_config(monkeypatch, tmp_path):
    """Brain._ensure calls config.load()+validate() — give tests a valid offline
    cfg so MCP tests never depend on a real config.toml (CI has none)."""
    import loci.mcp_server as mcp
    fake = make_cfg(tmp_path, [{"path": str(tmp_path)}])
    fake.llm["api_key"] = "test-key"
    fake.embed["api_key"] = "test-key"
    monkeypatch.setattr(mcp.config, "load", lambda path="config.toml": fake)
    return fake


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()
