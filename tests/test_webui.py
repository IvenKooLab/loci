"""Web UI tests: evidence formatting, ask callback, offline app construction.

Everything here is offline (FakeEmbedder); gradio is optional and tests that
need it are skipped when the [ui] extra is not installed."""
import pytest

from conftest import build_index, make_cfg, write_corpus


# [1] evidence panel formatting

def test_format_evidence_renders_source_section_and_text():
    from loci.webui import format_evidence
    hits = [{"source": "/n/01.md", "section": "本地部署", "text": "正文`code`内容"}]
    md = format_evidence(hits)
    assert "[1] 01.md > 本地部署" in md    # doc name only, not the full path
    assert "正文'code'内容" in md          # backticks neutralized: code fence survives


def test_format_evidence_empty_and_no_section():
    from loci.webui import format_evidence
    assert format_evidence([]) == "（无检索结果）"
    assert ">" not in format_evidence([{"source": "x.md", "section": "", "text": "t"}])


# [2] ask callback: search -> answer -> (reply, evidence)

def test_ask_fn_returns_reply_and_evidence(monkeypatch, tmp_path):
    import loci.retriever
    from loci.webui import make_ask_fn
    sources = write_corpus(tmp_path, {"a.md": "# A\n混合检索融合向量检索和BM25"})
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    monkeypatch.setattr(loci.retriever, "answer",
                        lambda llm_cfg, q, hits, history=None: "混合检索=两者融合")
    reply, evidence = make_ask_fn(cfg, retriever)("混合检索", [])
    assert "混合检索" in reply
    assert "a.md" in evidence and "A" in evidence


def test_ask_fn_empty_question(tmp_path):
    from loci.webui import make_ask_fn
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, {"a.md": "# A\n内容"}))
    _, _, retriever = build_index(cfg)
    assert make_ask_fn(cfg, retriever)("   ", [])[0] == "请输入问题"


def test_ask_fn_empty_index_guidance(tmp_path):
    from loci.webui import make_ask_fn
    cfg = make_cfg(tmp_path, [])
    _, _, retriever = build_index(cfg)
    reply, evidence = make_ask_fn(cfg, retriever)("任意问题", [])
    assert "nothing relevant" in reply
    assert evidence == "（无检索结果）"


def test_ask_fn_passes_recent_history_to_answer(monkeypatch, tmp_path):
    import loci.retriever
    from loci.webui import make_ask_fn
    sources = write_corpus(tmp_path, {"a.md": "# A\n混合检索融合向量检索和BM25"})
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    captured = {}
    monkeypatch.setattr(loci.retriever, "answer",
                        lambda llm_cfg, q, hits, history=None: captured.update(history=history))
    ask_fn = make_ask_fn(cfg, retriever)
    ask_fn("混合检索", [("你好", "你好，请问"), ("什么是RAG", "RAG是检索增强生成")])
    assert [m["role"] for m in captured["history"]] == \
        ["user", "assistant", "user", "assistant"]


# [3] stats sidebar + app construction (offline)

def test_stats_markdown_lists_pipeline_status(tmp_path):
    from loci.webui import stats_markdown
    sources = write_corpus(tmp_path, {"a.md": "# A\n内容"})
    cfg = make_cfg(tmp_path, sources)
    _, store, _ = build_index(cfg)
    md = stats_markdown(cfg, store)
    assert "chunks" in md and "hybrid" in md and "bm25 tokenizer" in md


def test_build_app_constructs_blocks_offline(tmp_path):
    pytest.importorskip("gradio")
    from loci.webui import build_app
    sources = write_corpus(tmp_path, {"a.md": "# A\n内容"})
    cfg = make_cfg(tmp_path, sources)
    cfg.llm["api_key"] = "test-key"      # build() constructs a real client (no calls)
    cfg.embed["api_key"] = "test-key"
    app = build_app(cfg)
    assert app is not None


# [4] config defaults + cli wiring

def test_config_defaults_include_webui(tmp_path):
    from loci import config
    p = tmp_path / "c.toml"
    p.write_text('[[sources]]\npath = "X"', encoding="utf-8")
    assert config.load(str(p)).webui == {"host": "127.0.0.1", "port": 7860}


def test_cmd_webui_passes_host_and_port(monkeypatch):
    import loci.cli as cli
    import loci.webui as webui
    from loci.config import Config
    called = {}
    monkeypatch.setattr(webui, "run_app",
                        lambda c, host=None, port=None: called.update(host=host, port=port))
    cli.cmd_webui(Config(), host="0.0.0.0", port=9999)
    assert called == {"host": "0.0.0.0", "port": 9999}
