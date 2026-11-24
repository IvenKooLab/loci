"""A [[sources]] path may name one file.

`loci ingest` used to refuse to run at all while a single-file source was
configured ("Source directory unavailable"), and the scanner — which probes
each root with os.listdir for permission blocks — raised NotADirectoryError
on a file. Governance already accepted file sources; nothing else did."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FakeEmbedder, make_cfg
from loci import cli, loaders
from loci.store import Store


def test_scan_sources_accepts_a_single_file(tmp_path):
    f = tmp_path / "README.md"
    f.write_text("# Readme\n\nhello world", encoding="utf-8")
    docs = loaders.scan_sources([{"path": str(f)}])
    assert [Path(d["path"]).name for d in docs] == ["README.md"]
    assert "hello world" in docs[0]["content"]


def test_ingest_indexes_a_file_source_and_still_refuses_a_missing_one(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n\nbody a", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("# Readme\n\nhello world", encoding="utf-8")
    cfg = make_cfg(tmp_path, [{"path": str(notes)}, {"path": str(readme)}])
    monkeypatch.setattr(cli, "build",
                        lambda cfg: (FakeEmbedder(), Store(cfg.store["path"])))

    cli.cmd_ingest(cfg)
    store = Store(cfg.store["path"])
    assert {Path(s).name for s in store.list_sources()} == {"a.md", "README.md"}

    cfg.sources.append({"path": str(tmp_path / "gone.md")})
    with pytest.raises(SystemExit, match="unavailable"):
        cli.cmd_ingest(cfg)
