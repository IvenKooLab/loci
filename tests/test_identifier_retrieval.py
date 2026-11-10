"""Identifier queries must find the literal string, not just "about users".

From the review thread on the launch post:

  Mehdi Mohseni — "the BM25 tokenizer is [a-z0-9]+, so user_id and user-id
  both turn into user + id"
  Dan Kornas — "I'd keep an exact-match path for identifiers alongside that.
  Searching for a specific symbol shouldn't depend on the semantic ranking."

Both halves are pinned here: the tokenizer fix (opt-in) and the always-on
exact-literal channel in fusion. No ChromaDB: a fake store exercises the real
`_fuse`, so these run anywhere.
"""
from __future__ import annotations

import pytest

from loci.retriever import Retriever, identifier_terms
from loci.tokenizers import default_tokenize, get_tokenizer


# ---------------------------------------------------------------- tokenizer

def test_default_tokenizer_is_frozen():
    """Installs that never set [bm25] tokenizer must keep old behaviour."""
    assert default_tokenize("user_id") == ["user", "id"]
    assert default_tokenize("user-id") == ["user", "id"]


def test_identifier_tokenizer_keeps_the_surface_form():
    tok = get_tokenizer("identifier")
    assert "user_id" in tok("the user_id field")
    assert "user-id" in tok("the user-id header")
    # additive: every default token is still emitted, recall cannot drop
    assert tok("the user_id field")[:3] == ["the", "user", "id"]


def test_identifier_tokenizer_does_not_double_plain_words():
    """`sht45` is already one default token; re-emitting it would skew BM25 TF."""
    tok = get_tokenizer("identifier")
    assert tok("SHT45 drift").count("sht45") == 1


def test_identifier_tokenizer_separates_underscore_from_hyphen():
    tok = get_tokenizer("identifier")
    underscore = set(tok("user_id"))
    hyphen = set(tok("user-id"))
    assert "user_id" in underscore and "user_id" not in hyphen
    assert "user-id" in hyphen and "user-id" not in underscore


# ---------------------------------------------------------------- extraction

@pytest.mark.parametrize("query,expected", [
    ("user_id", ["user_id"]),
    ("user-id", ["user-id"]),
    ("ERR_4021 when saving", ["err_4021"]),
    ("call api/v2/users", ["api/v2/users"]),
    ("SHT45 drift", ["sht45"]),
    # no identifier → no boost, so ordinary queries keep their old ranking
    ("how do we roll back a bad release", []),
    ("user id", []),
    ("meeting 2026 03 12", []),
    ("v2", []),
])
def test_identifier_terms(query, expected):
    assert identifier_terms(query) == expected


# ---------------------------------------------------------------- ranking

class FakeStore:
    """Minimal store surface `_fuse` touches."""

    path = "/tmp/fake-store"

    def __init__(self, docs: dict[str, str]):
        self.docs = docs

    def all_chunks(self):
        return list(self.docs), list(self.docs.values())

    def get_many(self, ids):
        return [{"id": i, "source": f"/notes/{i}", "section": "", "tags": "",
                 "text": self.docs[i], "distance": 0.5}
                for i in ids if i in self.docs]

    def query(self, vector, top_k):
        return []


class FakeEmbedder:
    def embed(self, texts):
        return [[0.0] for _ in texts]


corpus = {
    "a": "the user id column is set during signup; user table has id primary key",
    "b": "call the user_id field from the API response; user_id is a uuid",
    "c": "use user-id in the header when proxying to the legacy service",
    "d": "unrelated: the id of the document, user facing feature",
}


def _fused(query, vector_ranking, tokenizer="default"):
    store = FakeStore(corpus)
    r = Retriever(FakeEmbedder(), store, top_k=4, hybrid=True,
                  bm25_tokenizer=tokenizer)
    vhits = [{"id": cid, "source": f"/notes/{cid}", "section": "", "tags": "",
              "text": corpus[cid], "distance": 0.1} for cid in vector_ranking]
    return [h["id"] for h in r._fuse(vhits, query, fetch=4)]


def test_exact_identifier_beats_a_semantic_favourite():
    """`b` is ranked first by the vector channel; `c` is the only doc with
    `user-id`. Asking for the identifier must surface `c` first."""
    order = _fused("user-id", vector_ranking=["b", "a", "d", "c"])
    assert order[0] == "c"


def test_underscore_and_hyphen_queries_diverge():
    underscore = _fused("user_id", vector_ranking=["a", "d", "c", "b"])
    hyphen = _fused("user-id", vector_ranking=["a", "d", "c", "b"])
    assert underscore[0] == "b"      # the doc containing user_id
    assert hyphen[0] == "c"          # the doc containing user-id
    assert underscore[0] != hyphen[0]


def test_plain_queries_keep_their_vector_order():
    """No identifier in the query → no boost, ranking untouched."""
    order = _fused("document id feature", vector_ranking=["d", "a", "b", "c"])
    assert order == ["d", "a", "b", "c"]


def test_boost_only_promotes_and_never_drops_results():
    order = _fused("user_id", vector_ranking=["a", "d", "c", "b"])
    assert set(order) == set(corpus)     # nothing lost


def test_exact_match_can_surface_a_chunk_outside_the_candidate_set():
    """The literal path is a channel of its own: `c` is not in the vector
    results at all, yet it must appear because it contains the string."""
    order = _fused("user-id", vector_ranking=["b", "a"])
    assert "c" in order
