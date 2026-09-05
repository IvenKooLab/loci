# Architecture

One sentence: **files flow left-to-right into ChromaDB at `ingest` time, and
queries flow right-to-left out of it at `search`/`ask` time.**

```
                       ingest (write path)
config.toml ──► loaders ──► chunker ──► embedder ──► store ──► chroma_db/
               │            │
               │            └─ heading breadcrumbs, fenced-code protection,
               │               sliding-window fallback, frontmatter tags
               └─ .md/.txt/.pdf scan, YAML-frontmatter subset, sha1 hashing

                       ask / search (read path)
        query ──► embedder ─┐
                            ├─► retriever ──► answer ──► LLM ──► cited reply
   store.all_chunks() ──► bm25 ┘   (RRF,      (prompt      │
                                    optional   template)  └─ [source: path > section]
                                    LLM rerank)
```

## Modules

| File | Lines-ish | Responsibility |
|---|---|---|
| `src/loci/config.py` | 60 | TOML + defaults + env-var key overrides, `validate()` |
| `src/loci/loaders.py` | 100 | directory scan, encodings, frontmatter subset, PDF (optional) |
| `src/loci/chunker.py` | 90 | heading-aware split, breadcrumbs, code-fence protection, windowing |
| `src/loci/embedder.py` | 20 | OpenAI-compatible embeddings, batching, 4k-char truncation |
| `src/loci/store.py` | 90 | ChromaDB wrapper: hash bookkeeping, prune, upsert, query |
| `src/loci/bm25.py` | 60 | Okapi BM25 + CJK-aware tokenizer (native, no deps) |
| `src/loci/retriever.py` | 130 | RRF fusion, optional LLM rerank (fail-open), answer synthesis |
| `src/loci/cli.py` | 200 | argparse wiring + ingest/search/ask/chat/watch/stats/doctor |
| `src/loci/watcher.py` | 50 | `watch` loop — periodic rescans reusing the hash bookkeeping |
| `src/loci/mcp_server.py` | 170 | MCP over stdio: JSON-RPC framing, tool dispatch, lazy pipeline |
| `main.py` / `mcp_server.py` | 10 | entry points with the `sys.path` shim for the src layout |

## Invariants worth knowing before you touch anything

1. **Identity is `(source path, content hash)`.** Incrementality = compare the
   hash stored in chunk metadata against a fresh `loaders.file_hash`. Anything
   else (mtime, size) will drift.
2. **Chunk IDs are `f"{path}::{i}"`.** `upsert_chunks` deletes-then-adds a
   file's chunks, so re-indexing never duplicates.
3. **MCP stdout carries protocol only.** Tool implementations run with stdout
   redirected to a buffer (`Brain.ingest`); anything user-facing goes to stderr.
4. **Metadata is flat strings.** Tags are stored comma-joined and filtered
   client-side — deliberate, so Chroma version differences can't break filters.

## Recipes: extending the pipeline

- **New file format** → `loaders.py`: extend `_read_text()` to return text (or
  `None` to skip); everything downstream just works.
- **New retrieval signal** → produce a ranked `[(chunk_id, score)]` list and add
  it to `Retriever._fuse` as another RRF input.
- **New MCP tool** → add its schema to `TOOLS`, a method on `Brain`, and a line
  in `_call_tool`. Keep tool text self-contained: hosts see nothing else.
- **Swap the vector store** → reimplement `Store`'s seven public methods
  (`indexed_hash`, `list_sources`, `delete_file`, `prune`, `upsert_chunks`,
  `count`, `query`, `all_chunks`, `get_many`). The rest of the code only talks
  to that interface.
