"""Config loading: config.toml (recommended) + env-var overrides for keys.

Set LOCI_HOME to anchor a whole instance (config + chroma_db + memories +
wiki) at one directory regardless of the process's cwd — service managers
(launchd, cron, systemd) don't honor a wrapper script's `cd`. Without it,
relative paths resolve against the cwd as before."""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Neutral defaults: any OpenAI-compatible endpoint works (see
# config.example.toml for Zhipu / DeepSeek / Kimi / Ollama recipes). OpenAI
# ships as the default because its schema is the de-facto compatibility
# standard — every listed provider speaks it.
DEFAULTS = {
    "llm": {"base_url": "https://api.openai.com/v1",
            "api_key": "", "model": "gpt-4o-mini"},
    "embed": {"base_url": "https://api.openai.com/v1",
              "api_key": "", "model": "text-embedding-3-small"},
    "chunk": {"size": 800, "overlap": 100},
    "top_k": {"search": 5},
    "retrieval": {"hybrid": True, "rrf_k": 60, "rerank": False,
                  "rerank_provider": "llm",
                  "local_rerank_model": "BAAI/bge-reranker-base"},
    "bm25": {"tokenizer": "default"},
    "watch": {"interval": 30, "auto_summarize": False},
    "memories": {"path": "./memories"},
    "wiki": {"path": "./wiki"},
    "chat": {"auto_extract": True},
    "sync": {"remote": ""},
    "http": {"host": "127.0.0.1", "port": 8765, "token": "", "icons": "./icons",
             "query_log": ""},
    "store": {"path": "./chroma_db"},
    "state": {"path": "./state"},
    # Read-only governance defaults. Nothing here changes retrieval; it only
    # decides when `loci governance` starts calling a note stale.
    "governance": {"stale_days": 180},
}


@dataclass
class Config:
    llm: dict = field(default_factory=dict)
    embed: dict = field(default_factory=dict)
    chunk: dict = field(default_factory=dict)
    top_k: dict = field(default_factory=dict)
    retrieval: dict = field(default_factory=dict)
    bm25: dict = field(default_factory=dict)
    watch: dict = field(default_factory=dict)
    memories: dict = field(default_factory=dict)
    wiki: dict = field(default_factory=dict)
    chat: dict = field(default_factory=dict)
    sync: dict = field(default_factory=dict)
    http: dict = field(default_factory=dict)
    store: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    governance: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    harnesses: list = field(default_factory=list)   # [[harness]] entries
    auth: list = field(default_factory=list)        # [[auth.tokens]] entries

    def validate(self) -> None:
        problems = []
        if not self.llm.get("api_key"):
            problems.append('llm.api_key is not set (config.toml or env var BRAIN_LLM_API_KEY)')
        if not self.embed.get("api_key"):
            problems.append("embed.api_key is not set (or BRAIN_EMBED_API_KEY)")
        if not self.sources:
            problems.append("no sources configured — add at least one document directory")
        if problems:
            raise SystemExit("Missing configuration:\n  " + "\n  ".join(problems))


def load(path: str = "config.toml") -> Config:
    cfg = Config()
    for section, values in DEFAULTS.items():
        getattr(cfg, section).update(values)

    home = os.environ.get("LOCI_HOME")
    base = Path(home).expanduser() if home else None
    if base is not None and path == "config.toml":
        path = str(base / "config.toml")
    p = Path(path)
    cfg.config_path = str(p)
    if p.exists():
        raw = tomllib.loads(p.read_text(encoding="utf-8-sig"))
        for section in DEFAULTS:
            if isinstance(getattr(cfg, section), dict):
                getattr(cfg, section).update(raw.get(section, {}))
        raw_sources = raw.get("sources", [])
        # one malformed [[sources]] entry used to kill every command with a
        # TypeError/KeyError deep in the scan — skip it with a pointer instead
        if isinstance(raw_sources, list):
            kept = []
            for item in raw_sources:
                if isinstance(item, dict) and isinstance(item.get("path"), str) \
                        and item["path"].strip():
                    kept.append(item)
                else:
                    print(f"[warn] [[sources]] entry without a valid path "
                          f"skipped: {item!r}", file=sys.stderr)
            cfg.sources = kept
        else:
            print("[warn] [[sources]] is not a table array — none loaded",
                  file=sys.stderr)
        cfg.harnesses = raw.get("harness", [])
        cfg.auth = raw.get("auth", {}).get("tokens", [])
    else:
        print(f"[warn] {path} not found — using defaults "
              f"(first run: cp config.example.toml config.toml)", file=sys.stderr)

    if base is not None:
        # anchor relative runtime paths at LOCI_HOME so the same config works
        # from any cwd (chroma/store resolve against cwd otherwise)
        for section in ("store", "memories", "wiki", "state"):
            v = getattr(cfg, section).get("path")
            if v and not Path(v).expanduser().is_absolute():
                getattr(cfg, section)["path"] = str((base / v).resolve())
        # `icons` and `query_log` are also runtime files: without anchoring,
        # a relative query_log follows the *process cwd* instead of the
        # instance, so two instances launched from different shells silently
        # write their query history into different places — the exact bug the
        # "which LOCI_HOME did Codex hit?" query log exists to diagnose.
        for key in ("icons", "query_log"):
            v = cfg.http.get(key)
            if v and not Path(v).expanduser().is_absolute():
                cfg.http[key] = str((base / v).resolve())
        for s in cfg.sources:
            v = s.get("path")
            if isinstance(v, str) and v and not Path(v).expanduser().is_absolute():
                s["path"] = str((base / v).expanduser().resolve())

    # generated/curated directories (memories, wiki) are always part of the
    # index (cross-session, cross-IDE memory + consolidated wiki pages) —
    # appended unless the user already listed that path
    try:
        existing = {str(Path(s0["path"]).expanduser().resolve()) for s0 in cfg.sources}
        for section in ("memories", "wiki"):
            d = Path(str(getattr(cfg, section)["path"])).expanduser().resolve()
            if str(d) not in existing and d.exists():
                cfg.sources.append({"path": str(d)})
    except OSError:
        pass

    # env vars override keys so plaintext secrets never have to sit in the file
    if v := os.environ.get("BRAIN_LLM_API_KEY"):
        cfg.llm["api_key"] = v
    if v := os.environ.get("BRAIN_EMBED_API_KEY"):
        cfg.embed["api_key"] = v

    # numeric sanity: strings from sloppy TOML, negative or absurd values
    for key in ("size", "overlap"):
        try:
            cfg.chunk[key] = int(cfg.chunk[key])
        except (TypeError, ValueError):
            print(f"[warn] chunk.{key}={cfg.chunk[key]!r} is not an int — "
                  f"using {DEFAULTS['chunk'][key]}", file=sys.stderr)
            cfg.chunk[key] = DEFAULTS["chunk"][key]
    cfg.chunk["size"] = max(cfg.chunk["size"], 1)
    # anything past half the size produces more overlapping than new content
    # (overlap=size-1 is a 1-char step: ~len(text) near-identical chunks) —
    # the old clamp TO size-1 was exactly the bug it claimed to prevent
    half = cfg.chunk["size"] // 2
    if cfg.chunk["overlap"] > half:
        print(f"[warn] chunk.overlap ({cfg.chunk['overlap']}) > chunk.size/2 "
              f"({cfg.chunk['size']}) — clamping to {half} (steps below that "
              "index near-duplicate chunks over and over)",
              file=sys.stderr)
        cfg.chunk["overlap"] = half
    try:
        cfg.top_k["search"] = max(int(cfg.top_k["search"]), 1)
    except (TypeError, ValueError):
        cfg.top_k["search"] = DEFAULTS["top_k"]["search"]
    # rrf_k is the denominator of every fused score (1 / (rrf_k + rank + 1)):
    # -1 made each search die with ZeroDivisionError, a string with TypeError
    rrf_k = cfg.retrieval.get("rrf_k")
    if not (isinstance(rrf_k, int) and not isinstance(rrf_k, bool) and rrf_k >= 0):
        print(f"[warn] retrieval.rrf_k={rrf_k!r} is not a non-negative int — "
              f"using {DEFAULTS['retrieval']['rrf_k']}", file=sys.stderr)
        cfg.retrieval["rrf_k"] = DEFAULTS["retrieval"]["rrf_k"]
    # the registry is the source of truth: a hand-kept list here silently
    # rejected the `identifier` tokenizer
    from loci.tokenizers import known_tokenizers
    known_tokenizers = known_tokenizers()
    if cfg.bm25.get("tokenizer") not in known_tokenizers:
        print(f"[warn] bm25.tokenizer={cfg.bm25.get('tokenizer')!r} is not one of "
              f"{known_tokenizers} — using 'default'", file=sys.stderr)
        cfg.bm25["tokenizer"] = "default"
    return cfg
