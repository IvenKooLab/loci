"""The watch loop must not prune an offline source.

`cmd_ingest` refuses to touch the index while a configured source is
unavailable (an unplugged vault is not an empty vault); `ingest_once` had no
such guard. A vault that went offline while `loci watch` ran was skipped by
the scan, the prune read that as "every note was deleted", and its chunks
were wiped — unsearchable meanwhile, and re-embedded from scratch once the
vault came back."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import FakeEmbedder, make_cfg
from loci import cli, watcher
from loci.store import Store


def test_an_offline_source_keeps_its_chunks(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("# A\n\nbody a", encoding="utf-8")
    gone = tmp_path / "gone"
    gone.mkdir()
    (gone / "b.md").write_text("# B\n\nbody b", encoding="utf-8")
    cfg = make_cfg(tmp_path, [{"path": str(vault)}, {"path": str(gone)}])
    store = Store(cfg.store["path"])
    store.upsert_chunks([{"text": "body b", "section": "B"}], [[0.1] * 128],
                        str(gone / "b.md"), "hh")
    monkeypatch.setattr(cli, "build",
                        lambda cfg: (FakeEmbedder(), Store(cfg.store["path"])))

    shutil.rmtree(gone)                      # the vault went offline
    with pytest.raises(RuntimeError, match="unavailable"):
        watcher.ingest_once(cfg)

    assert {Path(s).name for s in store.list_sources()} == {"b.md"}
