# Competitive Landscape Study — September 2026

*Why this file exists: before shipping v0.2 we studied the high-star tools in the
"chat with your notes / personal RAG" space to decide what to build and — more
importantly — what *not* to build. Findings below are cited with exact star
counts pulled from the GitHub API on 2026-09-04.*

## 1. The landscape

| Project | Stars | Status | What it is |
|---|---:|---|---|
| [open-webui](https://github.com/open-webui/open-webui) | 150.9k | active | Self-hosted LLM chat platform with built-in RAG (Ollama/OpenAI front-end) |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 90.1k | active | RAG engine with deep document understanding (DeepDoc), web UI, Docker deployment |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | 65.6k | active | All-in-one desktop/Docker AI app, workspaces, agents, MCP support |
| [PrivateGPT](https://github.com/zylon-ai/private-gpt) | 57.5k | active | Private document Q&A (API + Gradio UI) |
| [Khoj](https://github.com/khoj-ai/khoj) | 37.1k | active | Self-hosted "AI second brain": web app + Obsidian/Emacs plugins, agents, automations |
| [Onyx (ex-Danswer)](https://github.com/onyx-dot-app/onyx) | 31.9k | active | Enterprise AI assistant with 40+ connectors, Docker/K8s |
| [Graphiti](https://github.com/getzep/graphiti) | 30.6k | active | Temporal knowledge-graph memory for agents, MCP server 1.0 |
| [kotaemon](https://github.com/Cinnamon/kotaemon) | 25.7k | active | Clean RAG web UI with PDF preview + in-context citation highlighting |
| [Reor](https://github.com/reorproject/reor) | 8.6k | **archived 2026-03** | Local-AI note-taking app (auto-linking, semantic search) |
| [Obsidian Copilot](https://github.com/logancyang/obsidian-copilot) | 7.7k | active | Obsidian plugin: vault QA, chat, writing |
| [Verba](https://github.com/weaviate/Verba) | 7.7k | **archived** | Weaviate's local RAG chat app |
| [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) | 5.4k | active | Obsidian plugin: local-embedding note discovery |

## 2. Five patterns

**P1 — The winners are platforms, and they are enormous.**
open-webui, AnythingLLM, RAGFlow: breadth (chat + agents + connectors + admin +
UI) won the stars. Their codebases are hundreds of thousands of lines with
Docker-first deployment. Nobody out-platforms them from behind.

**P2 — The lightweight end of the market is a graveyard.**
Reor (archived 2026-03) and Verba (archived) were the two most-starred
"small, local, personal" tools. Both died the same death: a GUI app has an
endless maintenance treadmill (bundled models, desktop builds, OS quirks), and
a small team cannot keep that alive next to free platform alternatives. A
third entry in that race is a losing move.

**P3 — Obsidian plugins thrive but keep hitting the same three walls.**
From issue trackers and community threads (Smart Connections #961 and friends,
plugin-comparison writeups, r/ObsidianMD):
1. **Privacy vs. hardware trade-off** — Copilot-style plugins ship your vault
   to a cloud LLM; local-embedding plugins want your laptop to sweat.
2. **Fragile indexing** — empty notes, odd encodings, or a reopen can hang the
   index; users discover breakage only when answers go stale.
3. **Single-app lock-in** — the index and the chat box live inside Obsidian;
   nothing else (another editor, a script, an agent) can query it.

**P4 — Citation UX is a proven differentiator.**
kotaemon's rise was driven substantially by "shows you exactly which sentences
the answer came from" (PDF preview + highlighting). RAGFlow markets
"grounded, citation-backed answers" as a headline feature. People do not just
want answers from their notes; they want to *trust and verify* them.

**P5 — MCP created a new distribution channel, and retrieval is a top use.**
The reference `modelcontextprotocol/servers` repo sits at 90k stars; Graphiti
(a memory backend for agents) reached 30k. Agents (Claude Desktop, IDE
assistants, CLI agents) increasingly want *your* knowledge as a tool. A
retrieval backend that any MCP host can mount gets a UI — chat, shortcuts,
agent workflows — from every host, for free, without shipping one.

## 3. The thesis we derived

> **Don't build another chat app. Build the memory layer that every chat app
> can mount.**

Concretely, loci's differentiation for v0.2:

1. **MCP-first.** The second brain is a tool any agent can use (`serve` over
   stdio). Claude Desktop, Cursor, Cline, or any MCP host becomes its chat UI.
   This is the channel P2's corpses never had.
2. **Honest smallness.** The core stays small enough to read in one sitting —
   no framework, no Docker, `pip install -r requirements.txt` (two runtime
   dependencies). Hackability is the feature P1 cannot offer.
3. **Citations always, with breadcrumbs.** Every answer and every search hit
   carries `file path > heading path > chunk` so claims are verifiable at a
   glance (P4, applied to a terminal/agent audience).
4. **Robust, inspectable indexing.** Defensive loaders (skip what can't be
   parsed, never hang), content-hash incrementality, real pruning of deleted
   files, and `stats` / `doctor` commands so the index is never a black box
   (anti-P3).
5. **Hybrid retrieval on by default.** Vector + BM25 fused with Reciprocal
   Rank Fusion — the table-stakes quality bar set by RAGFlow/kotaemon, in
   ~60 lines of native code (anti-"toy").
6. **BYO-key privacy.** The index never leaves the machine; only embedding and
   chat calls go out, to whatever OpenAI-compatible endpoint you choose; no
   telemetry, no accounts (anti-P3.1).

What we deliberately do **not** do (v0.2): build a web UI, bundle local
models, add connectors/user management, or compete with platforms on breadth.
That is the treadmill that killed P2.

## 4. Method note

Star counts were fetched from the GitHub REST API on 2026-09-04 (unauthenticated,
`repos/{owner}/{repo}` → `stargazers_count`, `archived`). Qualitative findings
come from project issue trackers, r/ObsidianMD and r/LocalLLaMA threads, and
vendor comparison pages linked above. Re-check the table before quoting it in
marketing material — this market moves fast.
