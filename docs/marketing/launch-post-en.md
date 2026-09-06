# Launch post — loci (EN)

*Ready-to-post draft for Hacker News (Show HN) and r/LocalLLaMA / r/ObsidianMD.
Post title options at the bottom. Adjust voice to taste before posting.*

---

**Show HN: loci – A memory palace for your files, with an MCP server**

Two thousand years ago, orators memorized speeches by walking through a palace
in their minds — each room holding one idea. I built the same trick for my
files. It's called **loci** (that's the name of the technique), it's ~300 lines
of plain Python, and your AI agents can mount it as a tool.

The problem it solves: my knowledge is scattered across a dozen directories —
project docs, an Obsidian vault, PDF reports, exported ChatGPT/Claude chats.
Every tool I tried wanted me to move my notes into *its* app, run *its* Docker
stack, or ship my vault to someone's cloud.

So before writing code I studied the field properly — 13 high-star tools
(open-webui 150k, RAGFlow 90k, AnythingLLM 65k, Khoj 37k, Graphiti 30k, …).
Full data in the repo (docs/research/competitive-landscape.md). Two findings
shaped everything:

1. **The winners are enormous platforms.** Nobody out-platforms them from behind.
2. **The lightweight end is a graveyard.** Reor (8.6k stars) and Verba (7.7k
   stars) — the two most-starred "small personal" tools — both got archived.
   GUI apps are a maintenance treadmill: bundled models, desktop builds, OS quirks.

So loci does the opposite of both: **no platform, no UI, no daemon.** It's a
retrieval backend that every chat app you already use can mount:

- **MCP-first**: `loci-mcp` exposes brain_search / brain_ask / brain_links /
  brain_stats / brain_ingest over stdio, plus resources and prompts. Claude
  Desktop, Cursor, Cline — any MCP host becomes loci's UI, for free. That's the
  distribution channel the archived tools never had.
- **Hybrid retrieval by default**: vector search fused with a ~60-line native
  BM25 (CJK-aware tokenizer) via Reciprocal Rank Fusion. On my bilingual test
  corpus: vector-only 9/10 hit@5 → hybrid 10/10. The eval harness ships in the
  repo so you can measure it on your own notes.
- **Citations you can audit**: every hit carries `file > heading` breadcrumbs,
  and `loci ask --verify` re-checks the answer claim-by-claim against the
  sources, marking each ✓ / ~ / ✗. RAG that shows its work.
- **Local-first, actually**: the index never leaves your machine. Works with
  any OpenAI-compatible API (Zhipu, DeepSeek, Kimi, OpenAI) — or 100% offline
  with Ollama, verified end-to-end.
- **Knows your formats**: Obsidian frontmatter tags, [[wikilinks]] (there's a
  link-graph command), PDFs including tables (PyMuPDF4LLM), .docx, and
  ChatGPT/Claude chat exports — each conversation becomes a searchable doc.

Quality signals: 131 offline tests (no API keys needed to run them), CI on
Python 3.11–3.13, packaging smoke, a built-in retrieval eval, and a `doctor`
command that checks your config/endpoints/store.

The "no LangChain" thing is deliberate: the whole pipeline fits in one sitting.
If you want to understand RAG internals — chunking, BM25, RRF fusion, reranking
(LLM pointwise or a local bge cross-encoder at ~30–70ms) — this is a codebase
you can actually read.

Repo: https://github.com/IvenKooLab/loci — MIT, `pip install loci-rag`.

I'd genuinely like feedback on two things: (1) does the MCP-as-UI bet hold up
for your workflow, or do you keep wishing for a tiny local web page? (2) what
file formats would make you switch from whatever you use now?

---

**Title options**

- Show HN: loci – A memory palace for your files, with an MCP server (agents query your notes)
- Show HN: I studied 13 high-star RAG tools, then built the opposite – 300 lines, no LangChain
- Reddit r/LocalLLaMA: loci – local-first hybrid-RAG over your notes/PDFs/chat exports, mountable by Claude Desktop/Cursor via MCP (fully offline with Ollama)
- Reddit r/ObsidianMD: loci – search across your vault *and* your project docs *and* your ChatGPT exports, from your terminal or any MCP host (Obsidian stays your editor)

**Posting notes**

- HN: Show HN posts do best 8–10am ET weekdays; be in comments the first 2 hours.
- r/LocalLLaMA: lead with the offline/Ollama angle and the eval numbers.
- r/ObsidianMD: lead with "Obsidian stays your editor"; avoid anything that
  sounds like replacing it.
