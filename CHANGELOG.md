# Changelog

## v0.2.0 — 2026-09-05

The "memory layer" release: hybrid retrieval, MCP server, and a test suite.

### Added
- **MCP server** (`mcp_server.py`): `brain_search` / `brain_ask` / `brain_ingest`
  over stdio with zero extra dependencies — mount the second brain in Claude
  Desktop, Cursor, Cline, or any MCP host
- **Hybrid retrieval**: native ~60-line BM25 (CJK-aware tokenizer) fused with
  vector search via Reciprocal Rank Fusion; on by default (`[retrieval]` in config)
- **Heading breadcrumbs**: chunks carry their heading path; search results and
  citations now show `file > section`
- **Frontmatter tags**: Obsidian-style `tags:` are indexed; `search --tag` filters
- **`chat`**: multi-turn Q&A loop with conversation memory (`/clear`, `/exit`)
- **`watch`**: keep the index current by polling sources — pure stdlib, no watchdog driver
- **`stats`**: chunks per source, models, retrieval settings
- **`doctor`**: health check for config, source dirs, embed/LLM endpoints and store;
  exits 1 when something is broken
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
