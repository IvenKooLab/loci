"""Watch-mode vector-space guard: `ingest_once` must refuse to write when the
configured embedding model no longer matches the collection — otherwise a
watch loop keeps failing with a raw chroma error every cycle forever after an
[embed] model change (cmd_ingest has had this guard; watch didn't)."""
from __future__ import annotations

import pytest

from loci import watcher
from conftest import FakeEmbedder, make_cfg, write_corpus


class GuardedStore:
    """Store double whose ensure_embed enforces the model it was seeded with."""

    seeded_with = "embedding-3"

    def __init__(self, tmp_path):
        self._hashes: dict[str, str] = {}

    def indexed_hash(self, path):
        return self._hashes.get(path)

    def prune(self, keep):
        return []

    def ensure_embed(self, model, dim, rebuild=False):
        if model != self.seeded_with:
            raise SystemExit(
                "embedding model changed: index was built with "
                f"{self.seeded_with}, config now has {model}. "
                "Re-run with --force to rebuild the index from scratch.")
        return


def test_ingest_once_surfaces_model_change_as_runtime_error(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, {"a.md": "# A\nalpha"}))
    store = GuardedStore(tmp_path)
    calls: list[list[str]] = []
    embedder = FakeEmbedder()

    monkeypatch.setattr(watcher.loaders, "scan_sources",
                        lambda sources: [{"path": str(tmp_path / "notes" / "a.md"),
                                          "hash": "h1", "content": "x",
                                          "tags": "", "links": "",
                                          "mtime": 0.0}])
    monkeypatch.setattr("loci.cli.build", lambda c: (embedder, store))

    cfg.embed["model"] = "embedding-2"          # different from seeded_with
    with pytest.raises(RuntimeError, match="embedding model changed"):
        watcher.ingest_once(cfg)


def test_ingest_once_skips_probe_when_nothing_changed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, {"a.md": "# A\nalpha"}))
    store = GuardedStore(tmp_path)
    # pre-index the file at its current hash: nothing pending → no probe
    store._hashes[str(tmp_path / "notes" / "a.md")] = "h1"

    probe_calls: list[list[str]] = []
    embedder = FakeEmbedder()
    monkeypatch.setattr(embedder, "embed",
                        lambda texts, batch=16: probe_calls.append(texts))
    monkeypatch.setattr(watcher.loaders, "scan_sources",
                        lambda sources: [{"path": str(tmp_path / "notes" / "a.md"),
                                          "hash": "h1", "content": "x",
                                          "tags": "", "links": "",
                                          "mtime": 0.0}])
    monkeypatch.setattr("loci.cli.build", lambda c: (embedder, store))

    assert watcher.ingest_once(cfg) == 0
    assert probe_calls == []                    # unchanged corpus: zero cost
