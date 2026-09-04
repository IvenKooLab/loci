# Roadmap

## Shipped

### v0.2 (2026-09-05) — the "memory layer" release

- [x] Hybrid retrieval: vector + native BM25 fused with Reciprocal Rank Fusion (on by default)
- [x] **MCP server** (pulled forward from v0.3): `brain_search` / `brain_ask` / `brain_ingest` over stdio
- [x] Heading-breadcrumb chunks and section-level citations
- [x] Obsidian frontmatter tags + `search --tag`
- [x] `watch` mode (pure polling, no watchdog dependency)
- [x] `chat` multi-turn loop with conversation memory
- [x] PDF loading (optional `pypdf` extra)
- [x] `stats` / `doctor` / `ingest --force`
- [x] 59-test offline suite + GitHub Actions CI (Python 3.11–3.13)

### v0.1 (2026-09-03) — MVP

- [x] Recursive directory scan + markdown heading-aware chunking
- [x] OpenAI-compatible embeddings / chat (Zhipu / DeepSeek / Kimi / OpenAI all work)
- [x] ChromaDB local persistence + content-hash incremental indexing
- [x] CLI: ingest / search / ask (answers carry citations)

## Next

- [ ] Reranking (LLM-based first, local bge-reranker later) — RRF fusion covers the basics today
- [ ] More loaders: docx, HTML, chat-export formats
- [ ] Per-source ingestion profiles (different chunk sizes per directory)
- [ ] Web UI — deliberately last: the MCP host ecosystem is the UI layer for now

## Explorations

- [ ] Knowledge-graph mode (Neo4j, GraphRAG experiment)
- [ ] Incremental embedding cache (only re-embed changed chunks, not whole files)

## Non-goals

- Cloud storage (your data leaving the machine defeats the point)
- Multi-user (this is *my* second brain — build your own, it's ~300 lines)
- Competing with all-in-one chat platforms on breadth — see
  [the competitive landscape study](research/competitive-landscape.md) for why
