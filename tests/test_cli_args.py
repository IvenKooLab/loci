"""CLI argument wiring: --top_k alias applies the same override as -k."""
import sys

import loci.cli as cli_module
from conftest import make_cfg


def _run_main(args, tmp_path, monkeypatch):
    captured = {}

    def fake_cmd_search(cfg, query, **kw):
        captured["top_k"] = cfg.top_k["search"]
        captured["kw"] = kw

    fake = make_cfg(tmp_path, [])
    fake.sources = [{"path": str(tmp_path)}]   # pass cfg.validate()
    fake.llm["api_key"] = "test-key"
    fake.embed["api_key"] = "test-key"
    monkeypatch.setattr(cli_module.config, "load", lambda path="config.toml": fake)
    monkeypatch.setattr(cli_module, "cmd_search", fake_cmd_search)
    monkeypatch.setattr(sys, "argv", ["loci", *args])
    cli_module.main()
    return captured


def test_search_top_k_alias_override(tmp_path, monkeypatch):
    captured = _run_main(["search", "--top_k", "7", "测试查询"], tmp_path, monkeypatch)
    assert captured["top_k"] == 7


def test_search_short_k_still_works(tmp_path, monkeypatch):
    captured = _run_main(["search", "-k", "3", "测试查询"], tmp_path, monkeypatch)
    assert captured["top_k"] == 3


def test_ask_top_k_alias_override(tmp_path, monkeypatch):
    captured = {}

    def fake_cmd_ask(cfg, question, **kw):
        captured["top_k"] = cfg.top_k["search"]

    fake = make_cfg(tmp_path, [])
    fake.sources = [{"path": str(tmp_path)}]   # pass cfg.validate()
    fake.llm["api_key"] = "test-key"
    fake.embed["api_key"] = "test-key"
    monkeypatch.setattr(cli_module.config, "load", lambda path="config.toml": fake)
    monkeypatch.setattr(cli_module, "cmd_ask", fake_cmd_ask)
    monkeypatch.setattr(sys, "argv", ["loci", "ask", "--top_k", "9", "测试问题"])
    cli_module.main()
    assert captured["top_k"] == 9
