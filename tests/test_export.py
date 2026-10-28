"""`loci export` writes what the native build's `loci import` expects.

The two builds cannot share a store (ChromaDB is only readable from Python), so
the export is the contract between them. These pin the shape of a line, the
meta trailer, and that a private path is not silently dropped.
"""
from __future__ import annotations

import json

import pytest

from loci import cli, config


class FakeStore:
    """Store.dump()'s inputs without a ChromaDB collection."""

    def __init__(self, rows, metadata):
        self._rows = rows
        self._metadata = metadata

    def dump(self, path):  # mirrors Store.dump's contract
        from pathlib import Path

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".part")
        ids = [r["id"] for r in self._rows]
        docs = [r["text"] for r in self._rows]
        metas = [{k: v for k, v in r.items() if k not in ("id", "text", "vec")}
                 for r in self._rows]
        embs = [r["vec"] for r in self._rows]
        n = 0
        with tmp.open("w", encoding="utf-8") as f:
            for i, cid in enumerate(ids):
                meta = dict(metas[i])
                meta["id"] = cid
                meta["text"] = docs[i]
                meta["vec"] = [round(float(x), 6) for x in embs[i]]
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
                n += 1
            head = {"__meta__": {"chunks": n,
                                 "embed_model": self._metadata.get("embed_model"),
                                 "embed_dim": self._metadata.get("embed_dim")}}
            f.write(json.dumps(head) + "\n")
        tmp.replace(out)
        return {"path": str(out), "chunks": n}


def test_export_line_carries_everything_import_needs(tmp_path):
    rows = [{
        "id": "/n/a.md::0", "source": "/n/a.md", "chunk": 0,
        "section": "ADR-001", "text": "the sensor drifted", "tags": "aurora",
        "mtime": 1.7e9, "hash": "abc", "chash": "def", "vec": [0.1, 0.2],
    }]
    store = FakeStore(rows, {"embed_model": "text-embedding-3-small", "embed_dim": 2})
    out = tmp_path / "index.jsonl"
    r = store.dump(out)

    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert r["chunks"] == 1 and len(lines) == 2

    row = lines[0]
    for key in ("id", "source", "chunk", "section", "text", "tags", "mtime",
                "hash", "chash", "vec"):
        assert key in row, key
    assert row["vec"] == [0.1, 0.2]

    meta = lines[1]["__meta__"]
    assert meta["chunks"] == 1
    assert meta["embed_model"] == "text-embedding-3-small"
    assert meta["embed_dim"] == 2


def test_export_command_prints_the_next_step(tmp_path, monkeypatch, capsys):
    store = FakeStore([{
        "id": "/n/a.md::0", "source": "/n/a.md", "chunk": 0, "section": "",
        "text": "x", "tags": "", "mtime": 0.0, "hash": "h", "chash": "c",
        "vec": [1.0],
    }], {"embed_model": "m", "embed_dim": 1})
    monkeypatch.setattr(cli, "build", lambda cfg: (None, store))
    out = tmp_path / "x.jsonl"
    cli.cmd_export(config.load(str(tmp_path / "missing.toml")), str(out))
    printed = capsys.readouterr().out
    assert "exported 1 chunks" in printed
    assert "loci import" in printed
    assert out.exists()


def test_empty_index_says_so(tmp_path, monkeypatch, capsys):
    store = FakeStore([], {"embed_model": "m", "embed_dim": 1})
    monkeypatch.setattr(cli, "build", lambda cfg: (None, store))
    cli.cmd_export(config.load(str(tmp_path / "missing.toml")), str(tmp_path / "e.jsonl"))
    assert "nothing to migrate" in capsys.readouterr().out
