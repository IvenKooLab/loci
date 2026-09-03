# second-brain-rag 🧠

**A queryable "second brain" for the project docs, notes, and chat logs scattered across a dozen directories.**

Local files → chunking → embeddings → retrieval → LLM answer with citations. The index lives entirely on your machine; only the embedding/chat calls go out, to any OpenAI-compatible API (Zhipu / DeepSeek / Kimi / OpenAI / …).

> **Why no LangChain?** The whole pipeline is ~300 lines of plain Python, which means every stage stays readable, hackable, and learnable. Reach for a framework when you actually need the orchestration — not before.
>
> **How does it relate to Obsidian?** It doesn't compete — the two layer up: Obsidian is the note-taking frontend (writing, backlinks, browsing), while this project is the **cross-vault search engine**. Point `sources` at any directories (Obsidian vaults, project docs, code-repo manuals, chat exports) and ask across all of them in one command. An MCP server is planned so agents can query it programmatically (see Roadmap). For Q&A inside a single vault, Obsidian's AI plugins already do the job — this covers what those plugins can't reach.

## Architecture

```
local document dirs (markdown/txt, recursive)
        │  ingest
        ▼
loaders ──► chunker (heading-aware split + sliding-window fallback) ──► embedder ──► store (ChromaDB, persistent)
        │  ask
        ▼
retriever (top-k similarity) ──► answer (LLM synthesis + cited sources)
```

## Quick start

Requires Python 3.11+ (uses the stdlib `tomllib`).

```bash
pip install -r requirements.txt

# 1. Configure: copy the example and fill in your values
cp config.example.toml config.toml
#    API keys, models, and the directories you want to index

# 2. Ingest (incremental — deduplicated by content hash, safe to re-run)
python main.py ingest

# 3. Plain retrieval (check chunking and recall quality, no LLM call)
python main.py search "how does the project keep dependencies minimal"

# 4. Ask (retrieval + LLM answer with citations)
python main.py ask "why does the index track files by content hash"
```

## Configuration

| Key | Meaning |
|---|---|
| `[llm]` | base_url / api_key / model — any OpenAI-compatible endpoint |
| `[embed]` | same; the model must be an embedding model (e.g. `embedding-3`) |
| `[[sources]]` | list of document directories, scanned recursively for `.md` / `.txt` |
| `[chunk]` | chunking params (default 800 chars / 100 overlap) |
| `[top_k]` | number of hits per search (default 5) |

API keys can also come from the environment variables `BRAIN_LLM_API_KEY` / `BRAIN_EMBED_API_KEY` (these override the config file).

## Design decisions

- **ChromaDB, local & persistent**: zero services, zero ops, works right after `pip install`; swap in Milvus when the corpus outgrows it
- **Incremental indexing**: files are tracked by content hash — only changed files get re-embedded, deletions are cleaned up automatically
- **Answers always cite**: every answer ends with source file paths, so claims stay traceable and verifiable
- **Keys never in code**: keys live in `config.toml` (gitignored) or environment variables

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) — MCP server, web UI, hybrid retrieval (BM25), reranking, PDF support.

## License

MIT
