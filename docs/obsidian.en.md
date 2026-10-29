# Connect an Obsidian vault to loci (Python build)

Obsidian keeps editing your Markdown; loci builds a separate index and exposes cited passages to AI clients through MCP. This guide describes the current source checkout. Back up your vault and start with a small, non-sensitive test corpus.

**Select data deliberately:** loci recursively scans supported files, including Markdown under `.obsidian`, other hidden folders, and some symlinked files. It does not honor Obsidian's exclusions. Your embedding provider receives indexed text; your chat provider receives the question and retrieved excerpts. Use a filtered copy or a safe subdirectory if the vault contains data you do not want indexed or sent to providers.

## Setup

Requires Python 3.11+. From the repository root:

```bash
python -m pip install -e .
mkdir -p "$HOME/loci-obsidian"
cp config.example.toml "$HOME/loci-obsidian/config.toml"
export LOCI_HOME="$HOME/loci-obsidian"
```

On Windows, copy the example config to an instance directory and set `$env:LOCI_HOME = 'C:/Users/name/loci-obsidian'` in PowerShell. Edit the existing `[llm]` and `[embed]` entries with your OpenAI-compatible chat and embedding endpoints and model names. Change the existing `[[sources]].path` to an absolute path to your filtered vault; remove unused example sources. For Chinese notes you can set the existing `[bm25] tokenizer` to `cjk_bigram`. Windows paths in TOML may use forward slashes.

Provide `BRAIN_LLM_API_KEY` and `BRAIN_EMBED_API_KEY` through the runtime environment or your client's secure environment configuration. Python validation currently requires both values even for local providers. Do not commit secrets. Changing embedding model requires rebuilding the index with `loci ingest --force`; back up the index first.

```bash
loci ingest
loci stats
loci search "keywords from a known note"
loci ask "What was the decision? Cite the file and section."
```

Check the returned file, heading and excerpt against the note. Re-run `loci ingest` after edits. If a configured source directory is unavailable, current builds stop before pruning; this does not detect every read or synchronization failure. Actual deleted files in an available directory are pruned from the index. Keep backups.

For an MCP client, find the executable using `which loci-mcp` (PowerShell: `Get-Command loci-mcp`) and configure:

```json
{
  "mcpServers": {
    "loci": {
      "command": "/absolute/path/to/loci-mcp",
      "env": { "LOCI_HOME": "/absolute/path/to/loci-obsidian" }
    }
  }
}
```

Supply the keys securely to the client process, restart it, and ask it to use `brain_search` on a known note and cite the returned path, section and text. `brain_ask` is also available in Python. Actual tool invocation depends on the client and its permissions. If unavailable, check the executable, instance directory, keys and ingest.

`loci ask --verify "question"` requests a further model-based check; neither this nor a citation-shaped answer guarantees correctness. Verify the original passage with `brain_search` or `loci search`.

## Compatibility and limitations

| Feature | Python | Rust native (current source) |
|---|---|---|
| Markdown and headings | Body indexed with section breadcrumbs | Supported in a separate SQLite index |
| frontmatter tags | Simple scalars, inline and multiline lists; not full YAML | Simple scalars and inline lists; multiline lists are not guaranteed |
| wikilinks | Targets recorded; embeds are not followed or expanded | Parsing differs; embeds are not expanded |
| attachments | PDF/DOCX require extras; image OCR needs `[ocr]` | PDF/DOCX/OCR unsupported; Markdown, text, HTML and org read as text |
| MCP | Includes `brain_search` and `brain_ask` | `brain_search`, `brain_stats`, `brain_ingest`, `brain_harness`; no `brain_ask` |
| Q&A | CLI, MCP and web | Web console; no CLI or MCP ask |
| storage | ChromaDB | SQLite; exchange through export/import, not direct sharing |

Aliases, block references, transclusion, complex YAML and plugin-generated formats are not guaranteed to retain full Obsidian semantics. Test against a sanitized sample of your own notes. See [native README](../native/README.md).

Run `python scripts/eval_obsidian.py` from the source checkout to measure exact file, heading and excerpt hit@1/hit@5 over a small synthetic vault. It uses a temporary index and deterministic test vectors, not a real model; it is a regression baseline, not evidence of real-world semantic or answer accuracy.
