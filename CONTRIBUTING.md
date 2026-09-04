# Contributing

Thanks for looking under the hood — that's the point of this project. The
core is ~300 lines and meant to be read.

## Development setup

```bash
git clone <this repo>
cd second-brain-rag
pip install -e ".[dev,pdf]"   # runtime deps + pytest + optional PDF support
pytest                        # fully offline — no API keys needed
```

## Ground rules

1. **No heavyweight frameworks.** If a feature needs LangChain/LlamaIndex to
   ship, it ships differently or not at all. Native code over abstractions.
2. **No new runtime dependency without a written justification** in the PR —
   currently: `openai` (SDK for any OpenAI-compatible endpoint) and `chromadb`
   (local vector store). Everything else (BM25, RRF, frontmatter, MCP, watch)
   is stdlib on purpose.
3. **Tests stay offline.** Use the hash-based `FakeEmbedder` from
   `tests/conftest.py` and monkeypatch `OpenAI` for LLM paths. A test suite
   that needs keys is a test suite that stops running.
4. **Fail-open, never hang.** Retrieval extras (rerank, hybrid) must degrade
   to plain results on any error — see `rerank_hits` for the pattern. Loaders
   skip what they can't parse and say so on stderr.
5. **Citations are sacred.** Any feature that surfaces content must carry
   `source > section` with it.

## Where things live

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module map and
step-by-step notes on extending the pipeline.

## Commit style

Short imperative subject, no signing-off ceremony: `feat: ...`, `fix: ...`,
`docs: ...`, `test: ...`.
