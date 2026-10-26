"""BM25 tokenizers behind a small registry, so `[bm25] tokenizer` in
config.toml picks one by name without touching the ranking code.

Three built-ins:

- ``default`` — latin/digit runs stay whole, CJK becomes single characters, and
  hyphenated latin compounds also index their joined form (``Wi-Fi`` → ``wi``,
  ``fi``, ``wifi``). Dependency-free; the historical behaviour plus that fix.
- ``cjk_bigram`` — CJK becomes overlapping bigrams, latin runs stay whole.
  ``检索`` matches inside ``全文检索`` while ``定期检查索引`` produces no
  ``检索`` bigram, so phrase-level precision arrives without a dictionary.
- ``jieba`` — word-level Chinese segmentation via the optional package. Precise
  when the query lands on a dictionary boundary, but it also splits
  ``全文检索`` into one token, so a ``检索`` query then matches nothing. Offered
  for callers who want it; ``cjk_bigram`` is the safer choice for Chinese.

Unknown names raise at lookup; ``config.load`` catches that earlier and falls
back to ``default`` with a warning.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_RUN = re.compile(r"[a-z0-9]+")
_HYPHENATED = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")

_registry: dict[str, object] = {}


def register(name: str):
    def deco(fn):
        _registry[name] = fn
        return fn
    return deco


@register("default")
def default_tokenize(text: str) -> list[str]:
    """Single-character CJK, whole latin words, plus joined hyphenates."""
    lowered = text.lower()
    tokens = _TOKEN.findall(lowered)
    # "Wi-Fi" indexes as wi + fi + wifi, so a `wifi` query and a `Wi-Fi` query
    # both find it — the split alone made the two mutually invisible
    tokens.extend(m.group(0).replace("-", "") for m in _HYPHENATED.finditer(lowered))
    return tokens


@register("cjk_bigram")
def cjk_bigram_tokenize(text: str) -> list[str]:
    """Overlapping CJK bigrams; a one-character run stays a single token."""
    lowered = text.lower()
    tokens = _LATIN_RUN.findall(lowered)
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


_warned_jieba = False   # warn once per process, not once per query


@register("jieba")
def jieba_tokenize(text: str) -> list[str]:
    """Word-level Chinese segmentation, falling back to `default` (with a
    one-time install hint) when the optional package is absent."""
    global _warned_jieba
    try:
        import jieba
    except ImportError:
        if not _warned_jieba:
            _warned_jieba = True
            print("[warn] bm25.tokenizer = 'jieba' but jieba is not installed — "
                  "falling back to the single-char tokenizer. "
                  "Install it with: pip install 'loci-rag[zh]'")
        return default_tokenize(text)
    jieba.setLogLevel(20)   # silence the "Building prefix dict" banner
    return [t for t in jieba.cut(text.lower()) if t.strip()]


def get_tokenizer(name: str = "default"):
    fn = _registry.get(name or "default")
    if fn is None:
        raise ValueError(f"unknown tokenizer {name!r} "
                         f"(known: {', '.join(sorted(_registry))})")
    return fn
