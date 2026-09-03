"""配置加载：config.toml（推荐）+ 环境变量覆盖密钥。"""
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
    "store": {"path": "./chroma_db"},
}


@dataclass
class Config:
    llm: dict = field(default_factory=dict)
    embed: dict = field(default_factory=dict)
    chunk: dict = field(default_factory=dict)
    top_k: dict = field(default_factory=dict)
    store: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)

    def validate(self) -> None:
        problems = []
        if not self.llm.get("api_key"):
            problems.append("llm.api_key 未配置（config.toml 或环境变量 BRAIN_LLM_API_KEY）")
        if not self.embed.get("api_key"):
            problems.append("embed.api_key 未配置（或 BRAIN_EMBED_API_KEY）")
        if not self.sources:
            problems.append("sources 未配置任何文档目录")
        if problems:
            raise SystemExit("配置缺失：\n  " + "\n  ".join(problems))


def load(path: str = "config.toml") -> Config:
    cfg = Config()
    for section, values in DEFAULTS.items():
        getattr(cfg, section).update(values)

    p = Path(path)
    if p.exists():
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        for section in ("llm", "embed", "chunk", "top_k", "store"):
            getattr(cfg, section).update(raw.get(section, {}))
        cfg.sources = raw.get("sources", [])
    else:
        print(f"[warn] 未找到 {path}，使用默认配置（首次使用请 cp config.example.toml config.toml）")

    # 环境变量覆盖密钥，避免明文进文件
    if v := os.environ.get("BRAIN_LLM_API_KEY"):
        cfg.llm["api_key"] = v
    if v := os.environ.get("BRAIN_EMBED_API_KEY"):
        cfg.embed["api_key"] = v
    return cfg
