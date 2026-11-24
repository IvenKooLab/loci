"""retrieval.rrf_k is arithmetic: 1 / (rrf_k + rank + 1).

chunk.size, chunk.overlap and top_k all get a "not an int → warn and use
the default" pass in config.load; rrf_k had none. `rrf_k = -1` made every
search die with ZeroDivisionError and a string made it TypeError — a config
typo took down every query with a traceback.
"""
from __future__ import annotations

import pytest

from loci import config
from loci.retriever import Retriever


def _load(tmp_path, monkeypatch, body):
    (tmp_path / "config.toml").write_text(body, encoding="utf-8")
    monkeypatch.setenv("LOCI_HOME", str(tmp_path))
    return config.load()


@pytest.mark.parametrize("value", ["-1", '"sixty"', "60.5", "-0.5"])
def test_a_rrf_k_that_is_not_a_non_negative_int_falls_back(tmp_path, monkeypatch, capsys, value):
    cfg = _load(tmp_path, monkeypatch, f"[retrieval]\nrrf_k = {value}\n")
    assert cfg.retrieval["rrf_k"] == config.DEFAULTS["retrieval"]["rrf_k"]
    assert "rrf_k" in capsys.readouterr().err


def test_a_valid_rrf_k_is_kept(tmp_path, monkeypatch):
    cfg = _load(tmp_path, monkeypatch, "[retrieval]\nrrf_k = 7\n")
    assert cfg.retrieval["rrf_k"] == 7
    r = Retriever(None, None, 5, rrf_k=cfg.retrieval["rrf_k"])
    assert [h["id"] for h in r._rrf_merge([[{"id": "a"}, {"id": "b"}]])] == ["a", "b"]
