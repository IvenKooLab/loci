# Roadmap

## v0.1 (current) — MVP

- [x] Recursive directory scan + markdown heading-aware chunking
- [x] OpenAI-compatible embeddings / chat (Zhipu / DeepSeek / Kimi / OpenAI all work)
- [x] ChromaDB local persistence + content-hash incremental indexing
- [x] CLI: ingest / search / ask (answers carry citations)

## v0.2 — usability

- [ ] File watching (watchdog) for automatic incremental updates
- [ ] Hybrid retrieval: vector + BM25 keyword
- [ ] Reranking (LLM-based first, local bge-reranker later)
- [ ] PDF / docx loaders
- [ ] Follow-up questions (multi-turn conversation memory)

## v0.3 — ecosystem

- [ ] **MCP server**: expose the second brain to any MCP host (Claude Desktop, IDE agents, …)
- [ ] Web UI (single-file local page)
- [ ] Knowledge-graph mode (Neo4j, GraphRAG experiment)

## Non-goals

- Cloud storage (your data leaving the machine defeats the point)
- Multi-user (this is *my* second brain — build your own, it's ~300 lines)
