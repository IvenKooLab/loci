"""Synthetic vault regression: real loader, ingest, index, retrieval and MCP."""
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from loci import cli, loaders
from loci.mcp_server import Brain, handle_message
from conftest import FakeEmbedder, make_cfg
from loci.store import Store

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("obsidian_eval", ROOT / "scripts/eval_obsidian.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_vault_loading_preserves_headings_tags_links_and_embeds():
    docs = loaders.scan_sources([{"path": str(evaluation.VAULT)}])
    doc = next(d for d in docs if d["path"].endswith("传感器决策.md"))
    assert doc["tags"] == "项目/硬件,decision"
    assert "日记/2025-03-12" in doc["links"]
    assert "测试照片" not in doc["links"]
    assert "![[附件/测试照片.png]]" in doc["content"]
    # Current scanner indexes Markdown inside .obsidian; keep this visible to
    # users instead of claiming Obsidian's configuration directory is excluded.
    assert any(Path(d["path"]).name == "fixture.md" for d in docs)


def test_offline_retrieval_baseline_has_the_exact_source_section_and_passage(tmp_path):
    cases = [json.loads(line) for line in evaluation.CASES.read_text(encoding="utf-8").splitlines()]
    rows = evaluation.evaluate(evaluation.make_index(evaluation.VAULT, tmp_path / "db"),
                               evaluation.VAULT, cases)
    assert len(rows) == 5
    assert all(row["rank"] is not None for row in rows), rows


def test_ingest_edit_and_mcp_search_ask_carry_real_citations(tmp_path, monkeypatch):
    vault = tmp_path / "Vault with spaces"
    shutil.copytree(evaluation.VAULT, vault)
    cfg = make_cfg(tmp_path, [{"path": str(vault)}])
    cfg.embed.update({"api_key": "test", "model": "fake"})
    cfg.llm.update({"api_key": "test", "model": "fake"})
    cfg.bm25["tokenizer"] = "cjk_bigram"
    embedder, store = FakeEmbedder(), Store(cfg.store["path"])
    monkeypatch.setattr(cli, "build", lambda cfg: (embedder, store))
    cli.cmd_ingest(cfg)
    retriever = cli.make_retriever(cfg, embedder, store)
    brain = Brain()
    brain._cfg, brain._retriever, brain._store = cfg, retriever, store

    def call(name, query):
        response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": name, "arguments": query}}, brain)
        assert not response["result"]["isError"], response
        return response["result"]["content"][0]["text"]

    question = "2400mAh 锂电池目标续航多少天？"
    result = call("brain_search", {"query": question})
    assert "传感器决策.md > 温室项目 > 电池方案" in result
    assert "目标续航 30 天" in result

    # Replace only the model call: verify the actual prompt includes the
    # retrieved passage and source/section, not that a real model obeys it.
    captured = {}
    def completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="30 天 [source: 传感器决策.md > 温室项目 > 电池方案]"))])
    monkeypatch.setattr("loci.retriever.OpenAI", lambda **kw: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=completion))))
    reply = call("brain_ask", {"question": question})
    assert "30 天" in reply and "传感器决策.md > 温室项目 > 电池方案" in reply
    prompt = captured["messages"][-1]["content"]
    assert "传感器决策.md | section: 温室项目 > 电池方案" in prompt
    assert "目标续航 30 天" in prompt

    note = vault / "Projects/传感器决策.md"
    note.write_text(note.read_text(encoding="utf-8").replace("目标续航 30 天", "目标续航 45 天"), encoding="utf-8")
    cli.cmd_ingest(cfg)
    result = call("brain_search", {"query": question})
    assert "目标续航 45 天" in result
    assert "目标续航 30 天" not in result


def test_missing_vault_keeps_index_unchanged(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    shutil.copytree(evaluation.VAULT, vault)
    cfg = make_cfg(tmp_path, [{"path": str(vault)}])
    cfg.embed.update({"api_key": "test", "model": "fake"})
    store, embedder = Store(cfg.store["path"]), FakeEmbedder()
    monkeypatch.setattr(cli, "build", lambda cfg: (embedder, store))
    cli.cmd_ingest(cfg)
    before = store.count()
    vault.rename(tmp_path / "vault-offline")
    import pytest
    with pytest.raises(SystemExit, match="index left unchanged"):
        cli.cmd_ingest(cfg)
    assert before > 0 and store.count() == before
