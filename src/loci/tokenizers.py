"""BM25 tokenizers behind a small registry, so `[bm25] tokenizer` in
config.toml picks one by name without touching the ranking code.

Four built-ins. ``default`` is frozen: an install that never touches
``[bm25]`` must keep returning exactly what it returned in v0.8.1, so every
improvement ships under a new name and nobody is opted in silently.

- ``default`` — latin/digit runs whole, CJK as single characters. The historical
  tokenizer, unchanged.
- ``hyphen_join`` — ``default`` plus the joined form of hyphenated compounds
  (``Wi-Fi`` → ``wi``, ``fi``, ``wifi``), so both spellings find each other.
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
    """Whole latin/digit runs, CJK as single characters.

    Byte-for-byte the tokenizer this project has always used. Do not "improve"
    it: installs that never set `[bm25] tokenizer` must keep returning exactly
    the results they returned before. New behaviour goes in a new name.
    """
    return _TOKEN.findall(text.lower())


@register("hyphen_join")
def hyphen_join_tokenize(text: str) -> list[str]:
    """`default`, plus the joined form of hyphenated compounds.

    "Wi-Fi" indexes as wi + fi + wifi, so both a `wifi` query and a `Wi-Fi`
    query find it — under `default` the two spellings are mutually invisible.
    Opt in with `[bm25] tokenizer = "hyphen_join"`; it adds recall, so rankings
    for documents containing hyphens differ from `default`.
    """
    lowered = text.lower()
    tokens = _TOKEN.findall(lowered)
    tokens.extend(m.group(0).replace("-", "") for m in _HYPHENATED.finditer(lowered))
    return tokens


@register("cjk_bigram")
def cjk_bigram_tokenize(text: str) -> list[str]:
    """Overlapping CJK bigrams, whole latin runs, joined hyphenates.

    A one-character CJK run stays a single token. Intended for mixed
    Chinese/English notes: it is the only tokenizer where `wifi` and `Wi-Fi`
    meet and `检索` finds `全文检索`.
    """
    lowered = text.lower()
    tokens = _LATIN_RUN.findall(lowered)
    tokens.extend(m.group(0).replace("-", "") for m in _HYPHENATED.finditer(lowered))
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
