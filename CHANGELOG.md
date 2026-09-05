# Changelog

## v0.2.0 — 2026-09-05

The "memory layer" release: hybrid retrieval, MCP server, and a test suite.

### Added
- **MCP server** (`mcp_server.py`): `brain_search` / `brain_ask` / `brain_ingest`
  over stdio with zero extra dependencies — mount the second brain in Claude
  Desktop, Cursor, Cline, or any MCP host
- **Hybrid retrieval**: native ~60-line BM25 (CJK-aware tokenizer) fused with
  vector search via Reciprocal Rank Fusion; on by default (`[retrieval]` in config)
- **Optional LLM reranking** (`[retrieval] rerank` or `--rerank`): pointwise
  0–3 relevance scoring of fused candidates; fails open to the fused order on
  any error
- **Packaging** (`pyproject.toml`): `pip install second-brain-rag` installs
  `second-brain` and `second-brain-mcp` console commands
- **Local cross-encoder reranking** (`--rerank local`): BAAI/bge-reranker-base
  via the optional `rerank` extra (`sentence-transformers`); ~30–70 ms for 5
  pairs on GPU, offline and free vs the LLM provider's extra call. Provider
  configurable via `[retrieval] rerank_provider`, per-call via `--rerank llm|local`
- **Chat-log loader**: ChatGPT and Claude exports (`conversations.json`) in any
  source directory expand into one document per conversation, tagged `chatlog`
- **Per-directory chunk config**: `[[sources]]` entries accept `chunk_size` /
  `chunk_overlap` overrides (deliberate `overlap = 0` is honored)
- **Office/PDF understanding**: `.pdf` pages extract as markdown with tables as
  pipe rows via PyMuPDF4LLM (pypdf plain-text fallback); `.docx` paragraphs and
  table rows via the `[docx]` extra
- **MCP resources**: `resources/list` + `resources/read` expose `brain://stats`
  and one `brain://note/…` resource per indexed file (raw markdown)
- **MCP prompts**: three ready-made templates — `brain-briefing`, `study-plan`,
  `contradiction-check` — via `prompts/list` + `prompts/get`
- **Query operators** on `search` and `ask`: `--in` (path substring),
  `--since YYYY-MM[-DD]` (file modification time), `-e "exact phrase"`,
  combinable with `--tag` and `--rerank`; file mtimes are indexed metadata now
- **`ask --verify`** (and `brain_ask verify=true`): after answering, audit the
  answer claim-by-claim against the retrieved excerpts — ✓ supported,
  ~ partial, ✗ unsupported — to catch hallucinations the citations alone
  don't reveal. Fails open: if the audit call fails, the answer still prints
- **Verified fully-offline mode**: point `base_url` at a local Ollama
  (`http://localhost:11434/v1`) and the whole pipeline — embeddings, hybrid
  retrieval, answers — runs with zero cloud calls (end-to-end tested with
  `all-minilm` + `qwen2.5:0.5b`)
- **Retrieval eval harness** (`scripts/eval_retrieval.py`): hit@k comparison of
  vector-only vs hybrid on your own labeled queries — the README number comes
  from running it on a real 174-chunk corpus (10 bilingual queries: 9/10 → 10/10)
- **CONTRIBUTING.md** and **docs/ARCHITECTURE.md**: module map, invariants,
  and extension recipes
- **Heading breadcrumbs**: chunks carry their heading path; search results and
  citations now show `file > section`
- **Frontmatter tags**: Obsidian-style `tags:` are indexed; `search --tag` filters
- **`chat`**: multi-turn Q&A loop with conversation memory (`/clear`, `/exit`)
- **`watch`**: keep the index current by polling sources — pure stdlib, no watchdog driver
- **`stats`**: chunks per source, models, retrieval settings
- **`doctor`**: health check for config, source dirs, embed/LLM endpoints and store;
  exits 1 when something is broken
- **Wikilink graph**: `[[wikilink]]` targets are indexed; the new `links`
  command (and `brain_links` MCP tool) shows what a note links to and what
  links back — Obsidian's graph view, queryable from anywhere
- **`ingest --force`**: re-embed everything, ignoring content hashes
- **Optional PDF loading**: install `pypdf` and `.pdf` files in sources are indexed
- **Tests**: 59-test offline suite (hash-based fake embedder + real ChromaDB in temp
  dirs — no API keys needed) and a GitHub Actions CI matrix for Python 3.11–3.13
- **Research**: competitive landscape study of 13 high-star tools with exact star
  data and the positioning thesis behind v0.2 (`docs/research/competitive-landscape.md`)

### Fixed
- **Deleted files are now actually pruned** from the index — v0.1 claimed this but
  `store.delete_file` was never called for vanished files
- **Short notes are no longer silently dropped**: v0.1's <30-char fragment filter
  could make a one-line note invisible to search (found by the new test suite;
  window tails now merge into their neighbor instead of vanishing)

### Changed
- Fenced code blocks are never split mid-block (oversized blocks stay whole)
- Chunk metadata gained `section` and `tags`; re-run `ingest --force` once to
  rebuild an index made with v0.1
- The entire repository was translated to English (docs, code comments, CLI
  strings, commit history)

## v0.1.0 — 2026-09-03

Initial MVP: recursive directory scan, markdown heading-aware chunking with a
sliding-window fallback, OpenAI-compatible embeddings, ChromaDB persistence with
content-hash incremental indexing, and `ingest` / `search` / `ask` CLI commands
with cited answers.
