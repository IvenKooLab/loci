"""Config validation reads the tokenizer registry, not a hand-kept copy.

The `identifier` tokenizer is registered and documented ("opt in with
[bm25] tokenizer = \"identifier\""), but config.load checked a hard-coded
tuple that never listed it — so opting in produced a warning and a silent
downgrade to `default`.
"""
from __future__ import annotations

from loci import config, tokenizers


def _load(tmp_path, monkeypatch, body):
    (tmp_path / "config.toml").write_text(body, encoding="utf-8")
    monkeypatch.setenv("LOCI_HOME", str(tmp_path))
    return config.load()


def test_every_registered_tokenizer_is_selectable(tmp_path, monkeypatch):
    for name in tokenizers.known_tokenizers():
        cfg = _load(tmp_path, monkeypatch, f'[bm25]\ntokenizer = "{name}"\n')
        assert cfg.bm25["tokenizer"] == name, name
        assert callable(tokenizers.get_tokenizer(cfg.bm25["tokenizer"]))


def test_the_identifier_tokenizer_survives_config_load(tmp_path, monkeypatch):
    cfg = _load(tmp_path, monkeypatch, '[bm25]\ntokenizer = "identifier"\n')
    assert cfg.bm25["tokenizer"] == "identifier"


def test_an_unknown_name_still_falls_back_with_a_warning(tmp_path, monkeypatch, capsys):
    cfg = _load(tmp_path, monkeypatch, '[bm25]\ntokenizer = "klingon"\n')
    assert cfg.bm25["tokenizer"] == "default"
    assert "klingon" in capsys.readouterr().err
