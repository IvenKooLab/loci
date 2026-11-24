"""A long-lived Brain must survive the index being rebuilt under it.

`cmd_ingest` works through its own Store. With `--force` after an
embedding-model change that Store deletes and recreates the collection, and
every handle opened before — this Brain's store, its retriever's store —
then raises chroma's NotFoundError on every call until the process restarts.
The embedder would also still be the old model (same dimension: queries
silently in the wrong vector space).
"""
from __future__ import annotations

from pathlib import Path

import loci.cli as cli
import loci.mcp_server as mcp
from conftest import FakeEmbedder, make_cfg
from loci.store import Store

VEC = [0.1, 0.1, 0.1, 0.1]


def _brain(monkeypatch, cfg):
    cfg.llm["api_key"] = cfg.embed["api_key"] = "test-key"     # Brain._ensure validates
    monkeypatch.setattr(mcp.config, "load", lambda path="config.toml": cfg)
    monkeypatch.setattr(cli, "build",
                        lambda cfg: (FakeEmbedder(4), Store(cfg.store["path"])))
    brain = mcp.Brain()
    brain._ensure()
    assert brain._retriever is not None
    return brain


def _notes(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nalpha body", encoding="utf-8")
    return notes


def test_forced_ingest_through_the_same_brain_keeps_the_pipeline_live(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, [{"path": str(_notes(tmp_path))}])
    brain = _brain(monkeypatch, cfg)
    brain._store.ensure_embed("model-1", 4)
    brain._store.upsert_chunks([{"text": "stale chunk from the old model", "section": ""}],
                               [VEC], "old.md", "h")

    out = brain.ingest(force=True)

    assert "ingest failed" not in out, out
    assert brain._store.count() == 1
    assert {Path(s).name for s in brain._store.list_sources()} == {"a.md"}
    assert brain._store is brain._retriever.store
    assert "alpha body" in brain.search("alpha")


def test_a_rebuild_done_by_another_process_is_survived(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, [{"path": str(_notes(tmp_path))}])
    brain = _brain(monkeypatch, cfg)
    brain._store.ensure_embed("model-1", 4)
    brain._store.upsert_chunks([{"text": "alpha body", "section": ""}], [VEC], "a.md", "h")

    other = Store(cfg.store["path"])          # `loci ingest --force` in another process
    other.ensure_embed("model-2", 4, rebuild=True)
    other.upsert_chunks([{"text": "beta body", "section": ""}], [VEC], "b.md", "h")

    assert "beta body" in brain.search("beta")
    assert brain.store().count() == 1
