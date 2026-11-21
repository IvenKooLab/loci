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


def test_index_memory_file_refuses_on_model_change(tmp_path, monkeypatch):
    """The write paths (remember / chat auto-extract / harness summaries) go
    through index_memory_file: a model switch must surface actionable
    guidance, not a raw chroma dimension error."""
    from loci.memories import index_memory_file
    from conftest import FakeEmbedder

    cfg = make_cfg(tmp_path, [])
    cfg.embed["model"] = "embedding-2"
    store = GuardedStore(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("hello memory", encoding="utf-8")

    monkeypatch.setattr("loci.cli.build", lambda c: (FakeEmbedder(), store))
    with pytest.raises(SystemExit, match="--force"):
        index_memory_file(cfg, str(note))


def test_index_document_file_refuses_on_model_change(tmp_path, monkeypatch):
    """Uploads used to embed new-dimension vectors, hit the chroma error and
    then *delete the user's file*. The guard now refuses before any embed."""
    from loci.memories import index_document_file
    from conftest import FakeEmbedder

    cfg = make_cfg(tmp_path, [])
    cfg.embed["model"] = "embedding-2"
    store = GuardedStore(tmp_path)
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\nbody text", encoding="utf-8")

    monkeypatch.setattr("loci.cli.build", lambda c: (FakeEmbedder(), store))
    with pytest.raises(SystemExit, match="--force"):
        index_document_file(cfg, str(doc))


def test_brain_remember_survives_index_failure(tmp_path, monkeypatch):
    """write_memory lands the file BEFORE indexing; an index failure must
    answer with the stored path and a hint, never raise (the old code let
    the exception pierce the MCP tool after the file was already saved)."""
    from loci.mcp_server import Brain
    import loci.memories as memories_mod

    b = Brain.__new__(Brain)
    b._config_error = None

    class Cfg:
        memories = {"path": str(tmp_path / "memories")}
        store = {"path": str(tmp_path / "chroma")}
    b._cfg = Cfg()
    b._retriever = object()

    (tmp_path / "memories").mkdir()
    monkeypatch.setattr(memories_mod, "write_memory",
                        lambda *a, **k: str(tmp_path / "memories" / "n.md"))

    # model change: SystemExit guidance
    monkeypatch.setattr(memories_mod, "index_memory_file",
                        lambda *a, **k: (_ for _ in ()).throw(
                            SystemExit("embedding model changed: ... --force")))
    out1 = b.remember("hello")
    assert out1.startswith("stored:") and "--force" in out1

    # transient API failure: same shape, ingest picks it up later
    monkeypatch.setattr(memories_mod, "index_memory_file",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("connection error")))
    out2 = b.remember("hello again")
    assert out2.startswith("stored:") and "loci ingest" in out2
