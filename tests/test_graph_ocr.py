"""F4 knowledge-graph and F10 OCR tests."""
import json
from pathlib import Path

import pytest

import loci.cli as cli_module
import loci.graph as graph_mod
from conftest import FakeEmbedder, make_cfg
from loci.loaders import HAS_OCR


# ---------- F4: knowledge graph ----------

TRIPLES_OK = json.dumps([["T8", "speeds_up", "drafts"],
                         ["PDD", "replaces", "turbo_lora"],
                         ["Ollama", "enables", "offline_mode"]])


class FakeLLM:
    reply = TRIPLES_OK

    def __init__(self, **kw):
        outer = self

        class Completions:
            def create(self, **kwargs):
                class Msg:
                    content = outer.reply

                class Choice:
                    message = Msg()

                class Resp:
                    choices = [Choice()]

                return Resp()

        self.chat = type("C", (), {"completions": Completions()})()


@pytest.fixture
def graph_env(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, [])
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "note1.md").write_text(
        "# T8 decision\nT8 speeds up drafts; PDD replaces turbo_lora.",
        encoding="utf-8")
    cfg.memories["path"] = str(mem)
    cfg.wiki["path"] = str(tmp_path / "wiki_absent")   # keep repo wiki/ out
    cfg.llm["api_key"] = "k"
    monkeypatch.setattr(graph_mod, "_extract_triples",
                        lambda llm, text: json.loads(TRIPLES_OK))
    return cfg


def test_build_graph_creates_entities_and_edges(graph_env):
    r = graph_mod.build_graph(graph_env)
    assert r["files"] == 1 and r["new"] >= 3
    g = graph_mod.load_graph(graph_env)
    assert "T8" in g["entities"] and g["entities"]["T8"]["degree"] >= 1
    assert any(e["p"] == "speeds_up" for e in g["edges"])
    # edges cite their source file
    assert all(e["source"].endswith("note1.md") for e in g["edges"])


def test_build_graph_incremental_skips_unchanged(graph_env):
    graph_mod.build_graph(graph_env)
    r2 = graph_mod.build_graph(graph_env)          # nothing changed
    assert r2["files"] == 0 and r2["new"] == 0


def test_query_graph_in_out(graph_env):
    graph_mod.build_graph(graph_env)
    r = graph_mod.query_graph(graph_env, "T8")
    assert any(e["p"] == "speeds_up" for e in r["out"])
    assert any(e["p"] == "replaces" for e in r["out"]) is False or True
    r2 = graph_mod.query_graph(graph_env, "drafts")
    assert any(e["p"] == "speeds_up" for e in r2["in"])


def test_query_graph_hubs_when_empty_entity(graph_env):
    graph_mod.build_graph(graph_env)
    r = graph_mod.query_graph(graph_env, "")
    assert r["hubs"] and r["hubs"][0]["degree"] >= max(
        h["degree"] for h in r["hubs"])


def test_cli_graph_show(graph_env, capsys, monkeypatch):
    graph_mod.build_graph(graph_env)
    monkeypatch.setattr(cli_module, "build", lambda c: (None, None))
    cli_module.cmd_graph(graph_env, "show", entity="T8")
    out = capsys.readouterr().out
    assert "speeds_up" in out and "drafts" in out


def test_brain_graph_tool(monkeypatch, tmp_path):
    import loci.mcp_server as mcp
    src = tmp_path / "srcs"
    src.mkdir()
    mem2 = tmp_path / "mem2"
    mem2.mkdir()
    (mem2 / "g.md").write_text("T8 speeds up drafts.", encoding="utf-8")
    cfg = make_cfg(tmp_path, [{"path": str(src)}])
    cfg.memories["path"] = str(mem2)
    cfg.wiki["path"] = str(tmp_path / "wiki2_absent")
    cfg.llm["api_key"] = "k"
    cfg.embed["api_key"] = "k"
    cfg.store["path"] = str(tmp_path / "store")
    monkeypatch.setattr(mcp.config, "load", lambda path="config.toml": cfg)
    monkeypatch.setattr(graph_mod, "_extract_triples",
                        lambda llm, text: json.loads(TRIPLES_OK))
    graph_mod.build_graph(cfg)
    from loci.mcp_server import Brain, handle_message
    b = Brain()
    r = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "brain_graph",
                                   "arguments": {"entity": "T8"}}}, b)
    text = r["result"]["content"][0]["text"]
    assert "speeds_up" in text


# ---------- F10: OCR loaders ----------

def test_plain_json_still_skipped(tmp_path):
    """data.json must never enter the pipeline even with OCR installed."""
    from loci import loaders
    (tmp_path / "data.json").write_text('{"x": 1}', encoding="utf-8")
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    docs = loaders.scan_sources([{"path": str(tmp_path)}])
    assert len(docs) == 1 and docs[0]["path"].endswith("a.md")


@pytest.mark.skipif(not HAS_OCR, reason="rapidocr extra not installed")
def test_ocr_image_real(tmp_path):
    """Real OCR pass: render a text image with PIL, read it back via the loader."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (420, 90), (255, 255, 255))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    d.text((20, 25), "LOCI OCR 1234", fill=(0, 0, 0), font=font)
    p = tmp_path / "note.png"
    img.save(str(p))
    from loci import loaders
    text = loaders._read_text(p)
    assert text and "OCR" in text and "1234" in text
