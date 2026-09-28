"""BM25 tokenizers behind a tiny registry so config.toml can select one by name.

`default` splits CJK text into single characters — dependency-free, the
original behavior. `jieba` does word-level Chinese segmentation, which keeps
phrases like 向量检索 intact for BM25 matching; it imports the optional
`jieba` package lazily and degrades to `default` when it is not installed
(fail-open, per project ground rules)."""
from __future__ import annotations

import re

# Latin words stay whole; CJK text becomes single characters (strong enough
# for BM25 ranking and keeps the tokenizer dependency-free).
_TOKEN = re.compile(r"[a-z0-9]+|[一-鿿]")

_registry: dict[str, object] = {}


def register(name: str):
    def deco(fn):
        _registry[name] = fn
        return fn
    return deco


@register("default")
def default_tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@register("jieba")
def jieba_tokenize(text: str) -> list[str]:
    """Word-level Chinese segmentation. Falls back to `default` when the
    optional jieba package is not installed."""
    try:
        import jieba
        jieba.setLogLevel(20)   # silence the "Building prefix dict" banner
    except ImportError:
        return default_tokenize(text)
    return [t for t in jieba.cut(text.lower()) if t.strip()]


def get_tokenizer(name: str = "default"):
    fn = _registry.get(name or "default")
    if fn is None:
        raise ValueError(f"unknown tokenizer {name!r} "
                         f"(known: {', '.join(sorted(_registry))})")
    return fn
