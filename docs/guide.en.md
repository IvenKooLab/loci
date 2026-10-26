# Usage guide

[Back to README](../README.md)

## Model providers


`[llm]` and `[embed]` can point at different providers (chat via DeepSeek,
embeddings via OpenAI — mixing is fine). The only rule: the `[embed]` endpoint
must offer an OpenAI-style `/embeddings` API.

| Provider | `base_url` | chat model | embedding model | Notes |
|---|---|---|---|---|
| OpenAI *(default)* | `https://api.openai.com/v1` | `gpt-4o-mini` | `text-embedding-3-small` | |
| Zhipu (GLM) | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.6` | `embedding-3` | |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | — | no `/embeddings`; pair `[embed]` with another provider |
| Kimi (Moonshot) | `https://api.moonshot.cn/v1` | `kimi-k2` | — | same — pair `[embed]` elsewhere |
| Ollama *(local)* | `http://localhost:11434/v1` | `llama3.1`, `qwen2.5:7b`, … | `nomic-embed-text` | 100% offline; any api_key accepted |


## Demo

Real session, indexed against the docs of
[minimax-h3-turing](https://github.com/IvenKooLab/minimax-h3-turing)
(paths shortened for display):

```
$ python main.py search "what the 22G card can and cannot do" -k 3

[1] minimax-h3-turing/docs/en/01-hardware-limits.md > 01 · What a 2080Ti 22G Can and Cannot Do    (similarity 0.562)
[2] minimax-h3-turing/docs/en/02-w4a8-vs-w4a4.md > 02 · Quantization Measured > You Can Try Without 22G  (similarity 0.446)
[3] minimax-h3-turing/docs/en/01-hardware-limits.md > ... > 3. VRAM is just barely enough — manage it  (similarity 0.504)

$ python main.py ask "How should I choose between T8 aggressive mode and the final-render mode, and why?"

Answer:
* Drafts / preview / shot selection: use T8 aggressive mode — a 43% speedup
  (2.7 min/clip), and "a different picture of equal quality" is fine for picking shots.
* Final shots: use final-render mode (no T8). T8 makes the numerical trajectory
  fork, so re-running with the same seed produces a different clip — which breaks
  the reproducibility final outputs need.

[source: docs/en/08-t8-blockcache-4step.md > Practical Advice (4-step Turbo route)]
[source: docs/en/06-faq.md > 12. Cache-style accelerators break "same-seed re-runs"]
```

Hybrid retrieval means a Chinese query still finds the English doc (and vice
versa) — keyword evidence (`BM25`) catches what embeddings miss, and every
citation points at a **section**, not just a file.

### Does hybrid actually help? (mini-eval, 10 bilingual queries)

```
$ python scripts/eval_retrieval.py scripts/eval_cases.example.jsonl
vector-only: 9/10  →  hybrid: 10/10
```

Hybrid also fixed the #1 ranking on keyword-ish queries (e.g. "T8 block cache
threshold speedup": vector put an FAQ first, hybrid puts the actual T8
writeup first). Run it against your own corpus with your own cases file.

### Reranking: two providers

`--rerank` reorders the fused candidates for precision:

| Provider | How | Cost |
|---|---|---|
| `llm` (default) | pointwise 0–3 relevance scoring by your chat model | one extra LLM call |
| `local` | cross-encoder, via `pip install 'loci[rerank]'` | ~30–70 ms for 5 pairs on GPU — offline, free |

```bash
python main.py search "T8 speedup" --rerank          # provider from config
python main.py search "T8 speedup" --rerank local    # cross-encoder (BAAI/bge-reranker-base)
```

The local model downloads on first use (~1.1 GB; set `HF_ENDPOINT=https://hf-mirror.com`
if HuggingFace is slow in your region). Measured on a 2080 Ti, bilingual query.

### Office documents, PDF tables, web pages, org files, chat logs

- **PDFs**: with the `[pdf]` extra, PyMuPDF4LLM extracts pages as markdown —
  **tables come through as pipe rows** (plain pypdf text is the fallback)
- **Word**: with the `[docx]` extra, `.docx` paragraphs and table rows are indexed
- **HTML**: `.html` / `.htm` pages become text with headings preserved (stdlib
  `html.parser`, zero dependencies — `<meta charset>` honored, script/style skipped)
- **org-mode**: `.org` notes convert faithfully — `#+TITLE` becomes the h1 with
  `*`-sections nested under it, `#+FILETAGS` become searchable tags
- **Chat exports**: drop a ChatGPT or Claude `conversations.json` into any
  source directory — it becomes one searchable document per conversation,
  tagged `chatlog` (`search --tag chatlog` scopes to chat history)


## Commands

| Command | What it does |
|---|---|
| `demo` | offline tour over a bundled sample corpus — keyword-only, no config or key (`--no-input` for scripts) |
| `ingest` | scan sources, index new/changed files, prune deleted ones (`--force` re-embeds everything) |
| `search "query"` | retrieval only — ranked excerpts with `path > section` breadcrumbs |
| `ask "question"` | retrieval + LLM answer with `[source: path > section]` citations |
| `ask "…" --verify` | additionally audit the answer claim-by-claim against the sources (✓ supported, ~ partial, ✗ unsupported) |

Filter operators (combine freely, on `search` and `ask`):

| Flag | Filters to |
|---|---|
| `--tag foo` | files whose frontmatter tags contain `foo` |
| `--in docs/en` | files whose path contains the substring |
| `--since 2026-08` / `--since 2026-08-15` | files modified on/after that date |
| `-e "exact phrase"` | chunks containing the exact phrase |
| `-k N` | return N hits (default 5) |
| `links "note"` | show the `[[wikilink]]` graph around a note — outbound and inbound |
| `chat` | multi-turn Q&A loop with conversation memory (`/clear`, `/exit`) |
| `watch` | keep the index current by polling sources (interval in `[watch]`) |
| `ask "…" --rewrite` | LLM-rewrite the query (keyword + cross-language variants) before retrieval |
| `feedback good\|bad` | rate the chunks used in the last ask; bad-rated chunks sink in future results |
| `wiki --suggest` | suggest wiki-worthy topics that don't have a page yet |
| `bench cases.jsonl` | retrieval benchmark: hit@k, vector-only vs hybrid |
| `sync push\|pull` | sync memories/wiki across machines via git ([sync] remote) |
| `serve-http` | HTTP REST API (search/ask/remember/stats) with Bearer auth |
| `graph build` / `graph show ENTITY` | knowledge graph over memories/wiki (LLM-extracted triples in graph.json) |
| `stats` | what's in the index: chunks per source, models, retrieval settings |
| `doctor` | health check: config, source dirs, embed/LLM endpoints, store (exit code 1 on failure — CI-friendly) |
| `python mcp_server.py` | MCP server over stdio (see below) |


## One memory, every IDE

Because every MCP host mounts the *same* loci server (same `config.toml`, same
index), memory written from one tool is recalled from every other:

```bash
# Claude Code
claude mcp add loci -- loci-mcp
```

```jsonc
// Cursor / Cline / Qoder / Trae (mcpServers JSON — same shape everywhere)
{ "mcpServers": { "loci": { "command": "loci-mcp" } } }
```

Then, from any of them: *"remember that the staging password rotates on
Mondays"* → `brain_remember` → later, from a *different* IDE:
*"when does the staging password rotate?"* → answered, with the memory cited.
Memories live as plain markdown in the `memories` directory (git-friendly, no
lock-in) and are tagged `memory`, so `loci search --tag memory` scopes to them.

> **Cross-IDE tip**: set `LOCI_HOME` to the same instance directory in every host. This anchors config, index, memories and wiki regardless of the launch directory.



## Real-world deployments

Two production setups that informed loci's design:

- **Shared memory across AI coding tools** — two agents (different CLIs) mount
  the *same* loci MCP server; each tool's native memory directory is a
  `[[sources]]` entry, so memory written on one side is recalled from the
  other, and `brain_remember` writes land in the shared pool.
- **Chat-app → knowledge-base pipeline** — documents messaged to a bot are
  committed to a private git repo; every machine pulls that repo on a timer
  and keeps its *own* local loci index fresh, so anything sent from the phone
  is searchable from every IDE and agent minutes later. Along the way this
  surfaced a real-world quirk: chat-app transfers can corrupt one zip member
  of a `.docx` — loci now salvages the text instead of skipping the file.

Rule of thumb for multi-machine setups: **sync source files, never indexes or
keys**. The vector index is machine-local (rebuild it with `loci ingest`);
credentials never belong in the repo.


## Harness memory hub

Running several AI coding tools? Each keeps its own memory directory. loci
discovers them automatically — a built-in registry (ZCode, Codex, DeepSeek
Harness, Claude Code) is probed per machine (home dirs, app bundles,
`DSH_HOME`), and every hit shows up as a card with its real memory stats.
Nothing is invented on disk: a tool with no markdown memories simply shows
zero. To override detection or add another tool, register it explicitly:

```toml
[[harness]]
name = "zcode"
type = "zcode"                        # knows projects/*/memory/*.md
paths = ["~/.zcode/cli/memories"]
icon = "⚡"                            # emoji, or a file in the icons dir

[[harness]]
name = "my-tool"
type = "generic"                      # recursive *.md scan
paths = ["~/notes/from-my-agent"]
```

- `loci harness` — per-tool stats (files, indexed chunks, last update, digest
  freshness), zero LLM cost
- `loci harness --summarize` — distill each tool's memories into a digest note
  in the shared pool (`memories/harness/<name>.md`), fingerprint-gated: an
  unchanged tool costs nothing, so `watch` can refresh on every cycle with
  `[watch] auto_summarize = true`
- MCP `brain_harness` — same two actions from any agent ("how is every tool
  doing lately?")


## Web console

`loci serve-http` now ships a built-in console at `http://127.0.0.1:8765/ui`
(no extra dependencies, no build step): harness cards with icons, shared-memory
create/edit/soft-delete, index stats with one-click ingest & re-summarize, and
a search/ask box.

Access control via multiple tokens and roles in `config.toml`:

```toml
[[auth.tokens]]
token = "long-random-secret-1"
role = "admin"                        # + ingest, re-summarize, audit log
label = "my-laptop"

[[auth.tokens]]
token = "long-random-secret-2"
role = "viewer"                       # read-only browsing
label = "phone"
```

Roles stack: `viewer` (read) < `editor` (+ create/edit/delete memories)
< `admin` (+ ingest / re-summarize / audit). The legacy single `[http]` token
keeps working and maps to admin. On your own machine no login is needed —
anonymous connections from 127.0.0.1 are trusted as admin (disable with
`[http] local_admin = false` when serving behind a reverse proxy or SSH
tunnel, where remote traffic also arrives on loopback). Write and admin
actions are audited to the service log and to `GET /audit`. The console binds
to 127.0.0.1 like the API — reach it from other devices through an SSH tunnel
or a TLS reverse proxy. The UI toggles 中文/EN in the header.


## Mount it in any MCP host

Add to `claude_desktop_config.json` (Claude Desktop) or your MCP client's
config:

```json
{
  "mcpServers": {
    "loci": {
      "command": "python",
      "args": ["/path/to/loci/mcp_server.py"],
      "env": { "LOCI_HOME": "/path/to/instance" }
    }
  }
}
```

`LOCI_HOME` anchors config, index, memories and wiki at one directory — no
matter the process's cwd. Handy for MCP mounts and for running `serve-http`
under launchd/cron/systemd, where a wrapper script's `cd` wouldn't apply.

The server exposes ten tools:

| Tool | Purpose |
|---|---|
| `brain_search(query, k?, tag?, in?)` | ranked excerpts with breadcrumbs |
| `brain_ask(question, verify?)` | grounded answer with citations; `verify=true` adds a claim-by-claim audit |
| `brain_links(note)` | outbound/inbound `[[wikilink]]` graph around a note |
| `brain_stats()` | index overview (chunks per source) |
| `brain_graph(entity?)` | knowledge-graph relations for an entity (omit for hub entities) |
| `brain_remember(text, title?, tags?)` | **write a memory** — durable, shared across sessions and IDEs |
| `brain_forget(query)` | soft-delete matching memories (they go to a `.trash` folder) |
| `brain_harness(action, name?, force?)` | per-AI-tool memory stats, or refresh their digest notes |
| `brain_wiki(topic)` | **memory consolidation** — distill the index into a curated wiki page about a topic |
| `brain_ingest(force?)` | incremental re-index |

Beyond tools, the server speaks the full protocol:

- **Resources** — `resources/list` exposes `brain://stats` plus one
  `brain://note/…` resource per indexed file (raw markdown via `resources/read`)
- **Prompts** — three ready-made templates: `brain-briefing`, `study-plan`,
  `contradiction-check`; hosts render them with your topic pre-filled


## Fully offline with Ollama

The index is local by design — and the embedding/chat calls can be too. Any
OpenAI-compatible server works; [Ollama](https://ollama.com) is verified
end-to-end:

```toml
[llm]
base_url = "http://localhost:11434/v1"
api_key = "ollama"          # any non-empty placeholder
model = "qwen2.5:0.5b"

[embed]
base_url = "http://localhost:11434/v1"
api_key = "ollama"
model = "all-minilm"
```

With this config, `ingest` / `search` / `ask` make zero cloud calls.
Swap in a bigger local chat model for better answers — the pipeline is
model-agnostic.


## Configuration

| Key | Meaning |
|---|---|
| `[llm]` | base_url / api_key / model — any OpenAI-compatible endpoint |
| `[embed]` | same; the model must be an embedding model (e.g. `text-embedding-3-small`) |
| `[[sources]]` | document directories, scanned recursively for `.md` / `.txt` / `.html` / `.org` (plus `.pdf`/`.docx`/images with the matching extras) |
| `[[sources]] chunk_size` / `chunk_overlap` | optional per-directory chunking override — wins over the global `[chunk]` block |
| `[chunk]` | chunking params (default 800 chars / 100 overlap) |
| `[top_k]` | number of hits per search (default 5) |
| `[retrieval]` | `hybrid` (vector+BM25 fusion, default on), `rrf_k`, `rerank` (LLM reranking, default off) |
| `[bm25]` | `tokenizer` for the lexical half: `default` (whole latin words, CJK single chars, hyphenates also joined), `cjk_bigram` (CJK bigrams — `检索` matches inside `全文检索`, recommended for Chinese notes), `jieba` (word segmentation, needs `loci-rag[zh]`) |
| `[watch]` | poll `interval` seconds |

API keys can also come from the environment variables `BRAIN_LLM_API_KEY` /
`BRAIN_EMBED_API_KEY` (these override the config file).


## Development

```bash
git clone https://github.com/IvenKooLab/loci && cd loci
pip install -e ".[pdf,docx]"        # editable install for hacking on loci
pip install -r requirements-dev.txt
pytest                              # fully offline, no API keys needed
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the ground rules (no frameworks,
tests stay offline, citations are sacred).

