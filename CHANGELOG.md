# Changelog

## Unreleased

### Added
- Read-side log: `GET /queries` and a **Queries** tab in the console. Writes
  were audited; reads were invisible, so "the agent gets nothing" had no
  explanation. Each row carries time, who, kind (`search`/`ask`), the query
  text, hit count, the top result's location and elapsed milliseconds — never
  the returned text. Newest 500 in memory; `[http] query_log` also appends
  them as JSONL. Logging can never fail a request.
- `loci serve-http --port 0` binds a free port and prints the one it got.
- Upload from the console: a **Sources** tab with a drop zone and file picker.
  Dropped files land in the instance's `memories/uploads/` and are indexed
  immediately — no `[[sources]]` edit, no full `ingest`, no rebuild. `.md`,
  `.txt`, `.html`, `.org` work out of the box; `.pdf`/`.docx`/images need the
  matching extra, which the tab lists from the server rather than guessing.
  Re-uploading a file you barely changed re-embeds only the changed chunks.
  Names are reduced to a bare filename (no traversal, no leading dot, no NUL),
  types are checked against the installed extras, bodies are capped at 16 MiB,
  and an existing name gets `-2` rather than being overwritten.
- The same tab lists every `[[sources]]` directory with its chunk count, so
  "which folder is this answer coming from" is answerable without the CLI.

### Fixed
- `[[harness]]` roots are scanned independently. A harness with several roots
  (Claude: `~/.claude/memories` plus a single `CLAUDE.md`) used to fall back to
  a *recursive* scan of its first root as soon as the harness as a whole found
  nothing, dragging deep subdirectory content into a preset defined as
  top-level only (`type = "codex"` means `*.md`).
- `paths` now accepts glob patterns (`paths = ["~/vault/**/*.md"]`), so a new
  tool needs config, not code. Glob roots keep their wildcard when resolved and
  contribute their non-wildcard prefix to chunk attribution.
- A port that is already in use names itself instead of surfacing a bare
  `OSError`: the message gives `lsof`, a free port to try, and the config key.
- The stale-digest badge tooltip read `badgeTip` literally — the i18n key was
  missing in both languages.

### Changed
- BM25 is built once per unchanged index instead of on every query. `_fuse`
  pulled every chunk out of the store and re-tokenized the whole corpus for
  each search: measured at 144 ms for 5k chunks and 291 ms for 10k, paid again
  on every keystroke in the console. The index is now cached and keyed on the
  store path, an in-process write counter (`Store` bumps it in `upsert_chunks`
  / `delete_file` / `reset`) and a digest of the chunk ids, so a CLI ingest, a
  `remember` or the console's own writes invalidate it immediately, and a
  second process writing the same directory is caught by the digest.
  Repeats drop to 7 ms at 5k chunks and 14 ms at 10k; ranking is unchanged,
  which is what the new tests assert.

### Added
- The version is now readable where people look for it: `loci --version`,
  a closing line in `loci doctor` (`loci 0.8.1 · python 3.12 · darwin`), the
  `serve-http` startup line, and a `v0.8.1` badge in the console header.
  `pyproject.toml` stays the only place the number is declared — the runtime
  reads installed metadata and falls back to that declaration for a source
  checkout, so the MCP handshake, the console and PyPI can no longer disagree
  after a release bump.
- Console evidence pane: clicking a search result opens the passage it came
  from, with the `file > section` breadcrumb, its tags, the similarity score
  and a copy-citation button (Esc closes it). `/search` now also returns
  `hits` alongside the unchanged `result` string, so the pane needs no extra
  retrieval; text-only clients and older console builds are unaffected.
- `loci demo`: a zero-configuration tour over six bundled fictional notes. It
  copies the corpus to `./loci-demo-notes`, chunks it with the real splitter
  and answers three example queries with BM25 only — no `config.toml`, no API
  key, no network. The point is a first run that works before a key is handed
  over; configuring `[embed]` later turns the same corpus hybrid. Ships as
  package data, so `pip install loci-rag && loci demo` is the whole setup.
  `--dir`, `--reset`, `--no-input` and `-k` cover scripting and CI.
- Pluggable BM25 tokenizers (`[bm25] tokenizer`), as opt-in names only. The
  lexical half of hybrid search is no longer hard-wired to CJK single
  characters, but **`default` is unchanged**: with no `[bm25]` section your
  rankings are identical to earlier releases. New names: `hyphen_join` (also
  indexes `wifi` for `Wi-Fi`), `cjk_bigram` (overlapping bigrams, so `检索`
  matches inside `全文检索` while `定期检查索引` stops producing a false hit;
  no dependency), and `jieba` (word segmentation, optional extra). `loci bench
  --tokenizer` runs an A/B on the same cases file. Registry from
  @hulinming's #2.

## v0.8.1 — 2026-10-19

### Fixed
- Web console file access now checks resolved directory components, blocking
  sibling directories with matching prefixes and symlinks escaping memory,
  harness-source, or icon roots. Memory listings omit escaped symlinks.
- HTTP write/admin backend failures return JSON errors instead of dropping
  the connection. POST requests reject malformed/non-object JSON, invalid
  content lengths, and bodies larger than 1 MiB before dispatch.

### Documentation
- Rebuilt all five README editions (English, Simplified/Traditional Chinese,
  Japanese and Korean) around setup, the Web console and MCP integration.
- Added light/dark console screenshots using fictional, isolated demo data,
  plus a read-only preview script to reproduce them without personal data.
- Moved detailed command and configuration references into usage guides.

### Packaging
- Aligned Python package and MCP registry versions at 0.8.1.

## v0.8.0 — 2026-10-17

Harness memory hub + built-in web console, from running loci as the shared
memory layer for several AI coding tools at once.

### Added
- **Harness memory hub**: AI tools are discovered automatically, Ekko-style —
  a built-in registry (ZCode, Codex, DeepSeek Harness, Claude Code) with
  per-machine probes (home dir / app bundle / `DSH_HOME`); detected tools show
  up with their real memory stats, nothing is invented on disk. `[[harness]]`
  config entries override the registry or add other tools (type presets know
  zcode's `projects/*/memory` layout, codex-style flat dirs, and generic
  recursive scanning). `loci harness` prints
  per-tool stats (files / indexed chunks / last update / digest freshness) with
  zero LLM cost; `loci harness --summarize` distills each tool's memories into
  a digest note in the shared pool, fingerprint-gated so unchanged harnesses
  cost nothing. New MCP tool `brain_harness` (stats | summarize)
- **Web console** at `http://127.0.0.1:8765/ui` (serve-http, zero new
  dependencies): harness cards with icons, shared-memory CRUD (create / edit /
  soft-delete to `.trash`), index stats with trigger buttons for ingest and
  re-summarize, search & ask box. Opens with no login on your own machine —
  anonymous loopback connections are trusted as admin (`[http] local_admin`,
  set `false` behind a reverse proxy/tunnel) — and the UI toggles 中文/EN
  (defaults to the browser language)
- **Multi-token access control**: `[[auth.tokens]]` entries with roles —
  viewer (read-only) < editor (+ memory writes) < admin (+ ingest /
  re-summarize / audit). The legacy single `[http]` token keeps working and
  maps to admin. Write and admin actions are audited to the service log and a
  `GET /audit` ring buffer
- **`watch --auto-summarize`** (`[watch] auto_summarize = true`): refresh
  harness digests on every poll cycle — the fingerprint gate makes no-change
  cycles free

## v0.7.0 — 2026-10-13

Hardening release, driven by the first production deployment (a zcode + codex
shared-memory setup running `serve-http` under launchd, `watch`-less, for
weeks) plus a provider-neutrality pass.

### Added
- **`LOCI_HOME`** environment variable: anchor config, index, memories and
  wiki at one directory regardless of the process's cwd — service managers
  (launchd/cron/systemd) and MCP mounts no longer need a wrapper `cd`.
  Born from a dual-node (Mac + ECS) deployment
- **`.docx` salvage**: when python-docx rejects a file (e.g. a broken zip CRC
  on some member after a chat-app transfer, while `word/document.xml` is
  intact), the loader now extracts paragraph text directly from the main part
  instead of skipping the file
- "Real-world deployments" section in the READMEs, with the multi-machine
  rule of thumb: sync source files, never indexes or keys
- **Embedding vector-space guard**: the index now fingerprints which embedding
  model/dimension built it. `ingest` refuses with actionable guidance when
  `[embed]` model changes, and `--force` truly drops and rebuilds the
  collection (previously it re-embedded into the old vector space and crashed
  mid-ingest with a raw chroma error). Same-dimension model swaps are caught
  too — they used to mix two vector spaces silently and poison retrieval.
  Legacy indexes are detected from their stored vectors, no rebuild required
- **Self-healing `serve-http`**: connection-class API failures rebuild the
  pipeline and retry the request once instead of failing forever — a long-lived
  process no longer pins clients created during a momentary network outage, and
  `config.toml` edits (keys, base URLs) are picked up without a restart
- Provider quick-reference table in the READMEs and copy-paste recipes in
  `config.example.toml`: OpenAI / Zhipu / DeepSeek / Kimi / Ollama (fully
  offline, any api_key accepted)
- Regression tests for the vector-space guard (`tests/test_store_guard.py`)

### Fixed
- HTTP API 500s now log a full traceback to stderr — systemd/launchd journals
  get the story (previously a bare `TypeName: message`, with request logging
  silenced)
- MCP `brain_ingest` no longer dies on `SystemExit` (e.g. the model-change
  guard above) — the tool returns the message instead of killing the server
- `__version__` was stuck at 0.6.2 while pyproject shipped 0.6.3; both now
  read 0.7.0

### Changed
- **Provider-neutral defaults**: `[llm]`/`[embed]` now default to the OpenAI
  endpoint (`gpt-4o-mini` / `text-embedding-3-small`) instead of Zhipu. Explicit
  `config.toml`s (anything copied from the example) are unaffected; a minimal
  config that only sets an api_key now targets OpenAI

## v0.6.3 — 2026-09-26

### Fixed
- `cmd_ask` now accepts the `--rewrite` flag — every `loci ask --rewrite` call raised `TypeError` since v0.5.0 (first external contribution, by @hulinming, with regression test #1)

## v0.6.2 — 2026-09-19

### Fixed
- `serve-http`, `sync` and `bench` subcommands were missing from the CLI
  argument parser (dispatch existed, registration didn't) — found by the
  loci-dsh integration team
- HTTP API: exceptions inside handlers (e.g. an empty query reaching the
  embedder) now return a 500 JSON response instead of dropping the connection;
  malformed request bodies return 400; empty queries short-circuit with a hint
- `serve-http --host/--port` now default from the `[http]` config section as
  documented

### Added
- Ecosystem section in the README: [loci-dsh](https://github.com/IvenKooLab/loci-dsh)
  (visual plugin for DeepSeek Harness) is the first integration built on
  `loci serve-http`


## v0.6.1 — 2026-09-19

- Merge parallel development branches: knowledge graph + OCR + HTML/org-mode
  loaders + embedding-reuse regression tests, all in one release

## v0.6.0 — 2026-09-19 (superseded, incomplete)

### Added
- **Knowledge graph** (`loci graph build|show`, MCP `brain_graph`): LLM-extracted
  entity-relation triples from memories and wiki pages, stored in a
  human-readable `graph.json` next to the index — no graph database. Edges cite
  their source files; wiki generation now injects graph relations as extra
  context. Incremental per file (content-hash tracked); robust against LLMs
  wrapping JSON in code fences
- **OCR** (`[ocr]` extra, rapidocr): `.png/.jpg/.jpeg/.bmp/.webp/.tiff` files
  are recognized and indexed; scanned PDFs (near-empty text layer) fall back to
  per-page OCR automatically. `doctor` reports OCR availability
- **HTML loader**: `.html` / `.htm` via stdlib `html.parser` — headings become
  `#`-lines, `<li>` becomes `- `, script/style skipped, `<title>` surfaces only
  when the body has no headings; honors `<meta charset>` with a gb18030
  fallback for legacy Chinese exports (no new dependencies)
- **org-mode loader**: `.org` / `.org_archive` — `#+TITLE` becomes the h1 with
  `*`-sections shifted one level under it, `#+FILETAGS` become frontmatter
  tags, org links `[[url][desc]]` become markdown links (no new dependencies)
- Regression tests for chunk-level embedding reuse (shipped in v0.5, now
  pinned by tests: editing one section re-embeds only that chunk)

## v0.5.0 — 2026-09-16

### Added
- **Auto memory extraction**: `loci chat` and `brain_ask` (with `extract=true`)
  distill durable facts from conversations into memory notes automatically (mem0
  pattern; max 3 per exchange, fail-open)
- **Query rewriting**: `loci ask --rewrite` / `brain_search rewrite=true` generates
  keyword and cross-language variants of the query, retrieves per variant, and
  RRF-fuses all results (fail-open on LLM errors)
- **Chunk-level incremental indexing**: only changed chunks are re-embedded;
  unchanged chunk vectors are reused via content-hash fingerprints (`chash`)
- **HTTP REST API**: `loci serve-http` exposes search/ask/remember/stats over
  JSON + Bearer auth; new `[http]` config section
- **Git memory sync**: `loci sync push|pull` — memories and wiki directories are
  git-managed for cross-machine memory sharing ([sync] remote in config)
- **Feedback loop**: `loci feedback good|bad` rates the chunks used in the last
  ask; penalised chunks are down-weighted in future retrieval
- **Wiki topic suggestions**: `loci wiki --suggest` surfaces index terms that
  cover enough chunks but don't have a wiki page yet
- **CLI wiring completed**: `--rewrite` flag on ask, `feedback` command with
  last-ask persistence, feedback penalties wired into retrieval (two real bugs
  found by the new tests: penalties were never applied, and rewrite defaulted
  to the rerank setting)

### Fixed
- Config warnings no longer leak into MCP stdout (moved to stderr)

## v0.4.0 — 2026-09-08

### Added
- **`brain_wiki` / `loci wiki "topic"` — memory consolidation**: distills
  everything the index knows about a topic into one curated, cross-linked wiki
  page (stored in `wiki/`, indexed immediately, retrievable like any source).
  Pages cite their sources, link related topics via [[wikilinks]], and
  regenerating a topic updates its page in place (self-citations excluded so
  pages cannot grow without bound — caught by tests)
- The wiki directory auto-joins the index ([wiki] in config), alongside
  memories
- **Verified on a real corpus**: generated a Chinese wiki page on "acceleration
  routes for H3 on 2080Ti" from 12 excerpts across the minimax-h3-turing docs
  (115 s end-to-end), with accurate facts and [[wikilinks]] — see
  docs/marketing/wiki-demo-cn.md
- **Fixed during development**: wiki regeneration cited the wiki's own previous
  version as material, growing the page without bound (self-references are now
  excluded from wiki material)


## v0.3.0 — 2026-09-07

### Added
- **Cross-session memory (write + recall)**: `brain_remember` (MCP tool) and
  `loci remember` store durable notes as markdown files in a configurable
  memories directory — written atomically, indexed immediately, and shared by
  every MCP host that mounts loci (Claude Code, Qoder, Trae, Cursor, Cline …).
  Write once, recall from anywhere: `brain_search` / `brain_ask` cover memories
  and documents alike (memories carry a `memory` tag; filter with `--tag memory`).
- **`brain_forget`** and soft-delete: matching memories move to a `.trash`
  folder instead of being destroyed
- Memories directory auto-joins the index ([memories] in config, default
  ./memories) and is covered by `watch`
- Verified cross-process: IDE A writes via one loci-mcp process, IDE B recalls
  through a completely separate process

## v0.2.5 — 2026-09-07

### Fixed
- **The server no longer dies in unconfigured environments.** Found via Glama's
  hosted inspection: the server started and answered introspection, but the first
  tool call ran `config.validate()` → `SystemExit`, killing the process, so the
  follow-up ping failed ("Connection closed"). All MCP tools now respond with
  setup guidance instead; resources degrade to `brain://stats` only.
- Config warnings now print to stderr — MCP hosts no longer see non-protocol
  text on stdout.

## v0.2.3 — 2026-09-06

- **PyPI distribution name is `loci-rag`** (`pip install loci-rag`; the import
  name stays `loci`) — `loci` itself was already taken on PyPI

## v0.2.2 — 2026-09-06

Bug-hunt batch: nine confirmed bugs found by systematic edge-case review,
each pinned by a regression test.

### Fixed
- **Chunker**: heading markers inside fenced code blocks (`# comment`) no longer
  split blocks or corrupt heading breadcrumbs
- **`--tag`**: exact match against the tag list — `--tag rag` no longer matches
  `storage`
- **`--in`**: path filter is separator-agnostic — `--in docs/en` now works against
  Windows backslash paths
- **MCP**: `brain_search`'s `k` override no longer leaks into later calls; string
  `k` from hosts is coerced
- **Stale chunks**: a file that becomes chunkless (e.g. frontmatter only) now has
  its old chunks deleted instead of lingering forever
- **`links`**: inbound matching is exact (Obsidian semantics) — short note names
  like `a.md` no longer substring-match unrelated link targets
- **Wikilinks**: Obsidian embeds (`![[image.png]]`) are excluded from the link graph
- **Chatlog loader**: duplicate conversation titles are disambiguated instead of
  silently overwriting each other
- **Config**: numeric sanity — string values are coerced, `overlap >= size` is
  clamped (with a warning), garbage falls back to defaults

### Changed
- CI installs the `[pdf,docx]` extras so the office/PDF-table tests actually run
  there (they were silently skipping)

## v0.2.1 — 2026-09-05

**Renamed to `loci`** — after the method of loci, the two-thousand-year-old
memory technique: place knowledge in locations, recall it by walking the path.
Python package, CLI (`loci`, `loci-mcp`), and repository are now `loci`;
`brain://` resource URIs are unchanged. No behavior changes.

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
- **Packaging** (`pyproject.toml`): `pip install loci` installs
  `loci` and `loci-mcp` console commands
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
