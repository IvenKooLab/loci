"""Native BM25 ranking with pluggable tokenizers. No dependencies by default."""
from __future__ import annotations

import math

from loci.tokenizers import default_tokenize, get_tokenizer


def tokenize(text: str) -> list[str]:
    """Backward-compatible alias for the default CJK single-char tokenizer."""
    return default_tokenize(text)


class BM25:
    """Okapi BM25 over a corpus of {key: text}, built once per process.

    `tokenizer` accepts a callable text->list[str]; defaults to the
    dependency-free CJK single-char tokenizer. Pass `get_tokenizer("jieba")`
    for word-level Chinese segmentation (requires the optional jieba package).
    """

    def __init__(self, corpus: dict[str, str], k1: float = 1.5, b: float = 0.75,
                 tokenizer=None):
        self.k1, self.b = k1, b
        self._tok = tokenizer or default_tokenize
        self.tf: dict[str, dict[str, int]] = {}
        self.dl: dict[str, int] = {}
        self.df: dict[str, int] = {}
        for key, text in corpus.items():
            toks = self._tok(text)
            freq: dict[str, int] = {}
            for t in toks:
                freq[t] = freq.get(t, 0) + 1
            self.tf[key] = freq
            self.dl[key] = len(toks)
            for term in freq:
                self.df[term] = self.df.get(term, 0) + 1
        n = len(self.dl)
        self.avgdl = (sum(self.dl.values()) / n) if n else 0.0
        self._n = n

    def score(self, query: str) -> list[tuple[str, float]]:
        """Return [(key, score)] sorted by descending BM25 score (positive only)."""
        results: list[tuple[str, float]] = []
        for key, freq in self.tf.items():
            dl = self.dl[key]
            if not dl:
                continue
            s = 0.0
            for term in self._tok(query):
                df = self.df.get(term)
                if not df:
                    continue
                idf = math.log(1 + (self._n - df + 0.5) / (df + 0.5))
                tf = freq.get(term, 0)
                if not tf:
                    continue
                s += idf * tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                results.append((key, s))
        results.sort(key=lambda x: -x[1])
        return results
