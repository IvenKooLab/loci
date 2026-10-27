# loci (native)

A native build of [loci](https://github.com/IvenKooLab/loci): the same hybrid
retrieval pipeline, with no Python runtime to install.

**Status: retrieval core + MCP server complete.** `loci-core`, the `loci` CLI
and the `loci-mcp` server work. The HTTP API and Tauri shell are next.

**MCP is the primary interface.** loci is listed as an MCP server (Glama and
elsewhere) and that is how it is meant to be used: mount it in Claude Desktop,
Cursor, Cline or any other host and the assistant gets the knowledge base as
tools. A console or a desktop shell are alternate front-ends to the same index
— never a requirement, never a replacement.

```json
{
  "mcpServers": {
    "loci": { "command": "/path/to/loci-mcp", "args": ["--config", "/path/to/config.toml"] }
  }
}
```

Tools: `brain_search` (hybrid retrieval, cited excerpts), `brain_stats` (what is
indexed), `brain_ingest` (pick up edited notes). Resources: `brain://stats` plus
one `brain://note/<urlencoded path>` per source file. Prompts: `brain-briefing`,
`contradiction-check`.

## Why a native build

The Python build depends on `chromadb` (a large native wheel) and an
interpreter, which makes "download and run" a multi-step install on Windows and
macOS. The retrieval half of loci is a few hundred lines of well-specified
behaviour, so it ports cleanly — and the index becomes one SQLite file instead
of a database directory.

## What is here

| crate | contents |
|---|---|
| `crates/loci-core` | chunking, tokenizers, BM25, embeddings, store, loader, indexer, retriever, config, **mcp** |
| `crates/loci-cli` | `loci` (demo / ingest / search / stats / doctor) and `loci-mcp` |

## Fidelity to the Python build

The port is behaviour-preserving where it matters and verified by tests:

- **Chunking** — heading breadcrumbs, fenced code never cut, sliding window for
  long prose, tiny tail windows merged.
- **`default` tokenizer is frozen** — latin runs whole, CJK single chars, and
  *no* hyphen joining. An instance that never chose a tokenizer must rank what
  it ranked before.
- **`cjk_bigram`** — overlapping CJK bigrams, so `检索` matches inside
  `全文检索` while `定期检查索引` produces no `检索` bigram. This is the one
  that fixes the decoy problem without a dictionary dependency.
- **BM25** — k1 = 1.5, b = 0.75, the same idf form.
- **RRF** — `rrf_k` = 60 over vector and lexical lists; only ranks are fused,
  because cosine distance and BM25 scores are not commensurable.
- **Incremental ingest** — content hashes skip unchanged files, per-chunk hashes
  reuse vectors, vanished files are pruned.

## Quick start

```bash
cargo run -p loci-cli -- demo        # offline tour, no key, no network
```

Then point it at real notes:

```toml
# config.toml
[embed]
api_key = "sk-…"
model = "text-embedding-3-small"

[[sources]]
path = "~/notes"
```

```bash
cargo run -p loci-cli -- ingest
cargo run -p loci-cli -- search "why did we drop the BME280"
cargo run -p loci-cli -- doctor
```

## Data is not shared with the Python build

This build stores chunks in SQLite (`index.db`); the Python build uses
ChromaDB. They do not read each other's index. A migration command is on the
list; until then, `loci ingest` re-indexes from the source directories, which is
cheap because the files are the source of truth.

## Building

Requires Rust 1.80+. See `crates/loci-core/src/*.rs` for per-module tests
(`cargo test`).

> On macOS 15+ with only Command Line Tools, the default SDK may ship `.tbd`
> stubs whose target list omits `arm64`, which makes every link fail with
> `unknown architecture`. `.cargo/config.toml` pins a working `SDKROOT`; adjust
> or delete it on your machine.
