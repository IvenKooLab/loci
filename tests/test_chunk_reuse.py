"""Regression cover for the chunk-reuse path (v0.5): a file edit must only
re-embed changed chunks, and an untouched file must not embed anything at all."""
import hashlib

import pytest

from loci import cli as cli_module
from loci.store import Store
from conftest import FakeEmbedder, make_cfg, write_corpus


class CountingEmbedder(FakeEmbedder):
    def __init__(self):
        super().__init__()
        self.embedded: list[str] = []

    def embed(self, texts, batch: int = 16):
        self.embedded.extend(texts)
        return super().embed(texts, batch)


DOC = (
    "# Alpha\n" + "alpha farming notes about planting seeds in spring. " * 6 +
    "\n# Beta\n" + "beta market notes about selling turnips for copper coins. " * 6 +
    "\n# Gamma\n" + "gamma wardrobe notes about hanfu sleeves and hairpins. " * 6
)


def test_reuse_map_fingerprints_and_hits(tmp_path):
    store = Store(str(tmp_path / "chroma"))
    chunks = [{"text": "hello world", "section": ""},
              {"text": "second chunk", "section": ""}]
    chashes = [hashlib.sha1(t["text"].encode()).hexdigest()[:16] for t in chunks]
    store.upsert_chunks(chunks, [[0.1] * 8, [0.2] * 8], "p", "fh", chashes=chashes)

    hashes, reuse = store.reuse_map("p", ["hello world", "changed text"])
    assert hashes[0] == chashes[0]                     # identical text → same fingerprint
    assert reuse[chashes[0]] == pytest.approx([0.1] * 8)  # vector carried over (float32)
    assert chashes[1] not in reuse                     # dropped chunk leaves no stale hit


def _ingest(cfg, store, embedder):
    import loci.cli as cli
    cli.build = lambda c: (embedder, store)  # noqa: F811 — offline wiring
    cli.cmd_ingest(cfg)


def test_edit_reembeds_only_the_changed_chunk(tmp_path, monkeypatch, capsys):
    sources = write_corpus(tmp_path, {"notes.md": DOC})
    sources[0]["chunk_size"] = 600            # one heading section per chunk
    cfg = make_cfg(tmp_path, sources)
    store = Store(cfg.store["path"])
    embedder = CountingEmbedder()
    monkeypatch.setattr(cli_module, "build", lambda c: (embedder, store))

    cli_module.cmd_ingest(cfg)
    assert len(embedder.embedded) == 3         # three sections, three embeddings

    edited = DOC.replace("selling turnips", "selling pumpkins")
    (tmp_path / "notes" / "notes.md").write_text(edited, encoding="utf-8")
    embedder.embedded.clear()
    cli_module.cmd_ingest(cfg)

    assert len(embedder.embedded) == 1         # only Beta was re-embedded
    assert "pumpkins" in embedder.embedded[0]
    assert store.count() == 3                  # index still holds all three chunks
    assert "reused 2 embeddings" in capsys.readouterr().out


def test_unchanged_file_embeds_nothing_on_reingest(tmp_path, monkeypatch):
    sources = write_corpus(tmp_path, {"notes.md": DOC})
    sources[0]["chunk_size"] = 600
    cfg = make_cfg(tmp_path, sources)
    store = Store(cfg.store["path"])
    embedder = CountingEmbedder()
    monkeypatch.setattr(cli_module, "build", lambda c: (embedder, store))

    cli_module.cmd_ingest(cfg)
    first = len(embedder.embedded)
    embedder.embedded.clear()

    cli_module.cmd_ingest(cfg)                 # nothing changed on disk
    assert first > 0
    assert len(embedder.embedded) == 0         # file-hash skip: zero embed calls
    assert store.count() == 3
