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
    "watch": {"interval": 30, "auto_summarize": False},
    "memories": {"path": "./memories"},
    "wiki": {"path": "./wiki"},
    "chat": {"auto_extract": True},
    "sync": {"remote": ""},
    "http": {"host": "127.0.0.1", "port": 8765, "token": "", "icons": "./icons"},
    "store": {"path": "./chroma_db"},
}


@dataclass
class Config:
    llm: dict = field(default_factory=dict)
    embed: dict = field(default_factory=dict)
    chunk: dict = field(default_factory=dict)
    top_k: dict = field(default_factory=dict)
    retrieval: dict = field(default_factory=dict)
    watch: dict = field(default_factory=dict)
    memories: dict = field(default_factory=dict)
    wiki: dict = field(default_factory=dict)
    chat: dict = field(default_factory=dict)
    sync: dict = field(default_factory=dict)
    http: dict = field(default_factory=dict)
    store: dict = field(default_factory=dict)
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
    if p.exists():
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        for section in DEFAULTS:
            if isinstance(getattr(cfg, section), dict):
                getattr(cfg, section).update(raw.get(section, {}))
        cfg.sources = raw.get("sources", [])
        cfg.harnesses = raw.get("harness", [])
        cfg.auth = raw.get("auth", {}).get("tokens", [])
    else:
        print(f"[warn] {path} not found — using defaults "
              f"(first run: cp config.example.toml config.toml)", file=sys.stderr)

    if base is not None:
        # anchor relative runtime paths at LOCI_HOME so the same config works
        # from any cwd (chroma/store resolve against cwd otherwise)
        for section in ("store", "memories", "wiki"):
            v = getattr(cfg, section).get("path")
            if v and not Path(v).expanduser().is_absolute():
                getattr(cfg, section)["path"] = str((base / v).resolve())
        v = cfg.http.get("icons")
        if v and not Path(v).expanduser().is_absolute():
            cfg.http["icons"] = str((base / v).resolve())
        for s in cfg.sources:
            v = s.get("path")
            if v and not Path(v).expanduser().is_absolute():
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
    if cfg.chunk["overlap"] >= cfg.chunk["size"]:
        print(f"[warn] chunk.overlap ({cfg.chunk['overlap']}) >= chunk.size "
              f"({cfg.chunk['size']}) — clamping to size-1 to avoid 1-char steps",
              file=sys.stderr)
        cfg.chunk["overlap"] = cfg.chunk["size"] - 1
    try:
        cfg.top_k["search"] = max(int(cfg.top_k["search"]), 1)
    except (TypeError, ValueError):
        cfg.top_k["search"] = DEFAULTS["top_k"]["search"]
    return cfg
