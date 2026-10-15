"""Gradio web UI over the same retrieval pipeline the CLI uses.

Requires the optional `ui` extra (gradio): `pip install 'loci-rag[ui]'`.
`loci webui` serves a chat pane next to the evidence chunks the answer was
grounded on, so every answer stays auditable."""
from __future__ import annotations

import os


def format_evidence(hits: list[dict]) -> str:
    """Render retrieved chunks as markdown evidence (doc name > section + text).

    The chat pane is for humans, so only the document name is shown here —
    the full path stays in the answer's [source: ...] citations."""
    lines: list[str] = []
    for i, h in enumerate(hits, 1):
        # document name only (chatlog sources keep their "path::title" suffix)
        src = h["source"].replace("\\", "/").rsplit("/", 1)[-1]
        where = f" > {h['section']}" if h.get("section") else ""
        lines.append(f"### [{i}] {src}{where}")
        lines.append("")
        lines.append("```")
        lines.append(h["text"][:400].replace("`", "'"))
        lines.append("```")
        lines.append("")
    return "\n".join(lines) if lines else "（无检索结果）"


def stats_markdown(cfg, store) -> str:
    """One-glance pipeline status for the sidebar."""
    return "\n".join([
        f"- **chunks**: {store.count()}",
        f"- **embed**: {cfg.embed['model']}",
        f"- **llm**: {cfg.llm['model']}",
        f"- **hybrid**: {cfg.retrieval['hybrid']}, rrf_k={cfg.retrieval['rrf_k']}",
        f"- **bm25 tokenizer**: {cfg.bm25.get('tokenizer', 'default')}",
    ])


def make_ask_fn(cfg, retriever):
    """ChatInterface callback: search -> answer with citations -> evidence panel."""
    def ask_fn(question: str, history: list) -> tuple[str, str]:
        from loci.retriever import answer
        if not (question or "").strip():
            return "请输入问题", "（无）"
        hits = retriever.search(question)
        if not hits:
            return "(nothing relevant in the knowledge base)", "（无检索结果）"
        msgs: list[dict] = []
        for turn in (history or [])[-4:]:   # keep the last four turns
            if isinstance(turn, dict):
                msgs.append(turn)
            elif isinstance(turn, (tuple, list)) and len(turn) >= 2:
                msgs.append({"role": "user", "content": str(turn[0])})
                msgs.append({"role": "assistant", "content": str(turn[1])})
        reply = answer(cfg.llm, question, hits, history=msgs or None)
        return reply, format_evidence(hits)
    return ask_fn


def build_app(cfg):
    """Build (not launch) the Gradio Blocks app for `loci webui` and tests."""
    import gradio as gr
    from loci.cli import build, make_retriever   # deferred: cli imports webui
    embedder, store = build(cfg)
    retriever = make_retriever(cfg, embedder, store)
    ask_fn = make_ask_fn(cfg, retriever)

    with gr.Blocks(title="loci — 本地知识库问答") as app:
        gr.Markdown("# loci 🧠 本地知识库问答")
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 索引状态")
                stats = gr.Markdown(stats_markdown(cfg, store))
                gr.Button("刷新状态").click(fn=lambda: stats_markdown(cfg, store),
                                            outputs=stats)
            with gr.Column(scale=3):
                gr.ChatInterface(
                    fn=ask_fn,
                    additional_outputs=[gr.Markdown(label="检索证据")],
                    description="答案基于右侧检索证据生成，引用指向源文档章节",
                )
    return app


def run_app(cfg, host: str | None = None, port: int | None = None) -> None:
    host = host or cfg.webui.get("host") or "127.0.0.1"
    port = port or int(cfg.webui.get("port") or 7860)
    print(f"loci webui: http://{host}:{port}")
    build_app(cfg).launch(server_name=host, server_port=port)
