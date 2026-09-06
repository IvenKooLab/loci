"""Config loading: config.toml (recommended) + env-var overrides for keys."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULTS = {
    "llm": {"base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "", "model": "glm-4.6"},
    "embed": {"base_url": "https://open.bigmodel.cn/api/paas/v4",
              "api_key": "", "model": "embedding-3"},
    "chunk": {"size": 800, "overlap": 100},
    "top_k": {"search": 5},
    "retrieval": {"hybrid": True, "rrf_k": 60, "rerank": False,
                  "rerank_provider": "llm",
                  "local_rerank_model": "BAAI/bge-reranker-base"},
    "watch": {"interval": 30},
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
    store: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)

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

    p = Path(path)
    if p.exists():
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        for section in DEFAULTS:
            if isinstance(getattr(cfg, section), dict):
                getattr(cfg, section).update(raw.get(section, {}))
        cfg.sources = raw.get("sources", [])
    else:
        print(f"[warn] {path} not found — using defaults "
              f"(first run: cp config.example.toml config.toml)")

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
                  f"using {DEFAULTS['chunk'][key]}")
            cfg.chunk[key] = DEFAULTS["chunk"][key]
    cfg.chunk["size"] = max(cfg.chunk["size"], 1)
    if cfg.chunk["overlap"] >= cfg.chunk["size"]:
        print(f"[warn] chunk.overlap ({cfg.chunk['overlap']}) >= chunk.size "
              f"({cfg.chunk['size']}) — clamping to size-1 to avoid 1-char steps")
        cfg.chunk["overlap"] = cfg.chunk["size"] - 1
    try:
        cfg.top_k["search"] = max(int(cfg.top_k["search"]), 1)
    except (TypeError, ValueError):
        cfg.top_k["search"] = DEFAULTS["top_k"]["search"]
    return cfg
