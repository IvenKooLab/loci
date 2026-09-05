from loci import config


def test_defaults_applied_without_file(tmp_path, capsys):
    cfg = config.load(str(tmp_path / "missing.toml"))
    assert cfg.chunk["size"] == 800
    assert cfg.retrieval["hybrid"] is True
    assert cfg.watch["interval"] == 30
    assert "warn" in capsys.readouterr().out


def test_file_overrides_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[chunk]\nsize = 400\n[[sources]]\npath = 'X'", encoding="utf-8")
    cfg = config.load(str(p))
    assert cfg.chunk["size"] == 400
    assert cfg.chunk["overlap"] == 100  # untouched default
    assert cfg.sources == [{"path": "X"}]


def test_env_vars_override_keys(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text('[llm]\napi_key = "file-key"', encoding="utf-8")
    monkeypatch.setenv("BRAIN_LLM_API_KEY", "env-key")
    monkeypatch.setenv("BRAIN_EMBED_API_KEY", "env-embed")
    cfg = config.load(str(p))
    assert cfg.llm["api_key"] == "env-key"
    assert cfg.embed["api_key"] == "env-embed"


def test_validate_collects_all_problems():
    cfg = config.Config()
    try:
        cfg.validate()
        raised = False
    except SystemExit as e:
        raised = True
        text = str(e)
    assert raised
    assert "llm.api_key" in text
    assert "embed.api_key" in text
    assert "sources" in text


def test_validate_passes_when_complete():
    cfg = config.Config()
    cfg.llm["api_key"] = "k"
    cfg.embed["api_key"] = "k"
    cfg.sources = [{"path": "x"}]
    cfg.validate()  # no SystemExit
