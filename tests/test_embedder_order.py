"""Vector assignment must follow the request order even when the endpoint's
response does not.

The OpenAI embeddings response carries an `index` per vector precisely so
consumers can reassemble; several OpenAI-compatible endpoints (self-hosted
routers among them) return `data` out of order. Appending in response order
silently stored chunk B's vector under chunk A — no error anywhere, just
quietly wrong retrieval. Reassemble by index and refuse a gap.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci.embedder import Embedder


class _D:
    def __init__(self, index, embedding):
        self.index, self.embedding = index, embedding


class _ShuffledEndpoint:
    """Returns each batch's vectors reversed — the order an endpoint must
    never be trusted for."""

    class embeddings:
        @staticmethod
        def create(model, input):
            n = len(input)
            return type("R", (), {"data": [_D(n - 1 - i, f"v{n - 1 - i}") for i in range(n)]})()


class _GappyEndpoint:
    class embeddings:
        @staticmethod
        def create(model, input):
            n = len(input)
            return type("R", (), {"data": [_D(i, f"v{i}") for i in range(n - 1)]})()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr("openai.OpenAI.__init__", lambda self, **k: None)


def test_out_of_order_response_is_reassembled_by_index():
    e = Embedder("http://x", "k", "m")
    e.client = _ShuffledEndpoint()
    assert e.embed(["A", "B", "C"]) == ["v0", "v1", "v2"]
    assert e.embed(["A", "B", "C", "D", "E"]) == ["v0", "v1", "v2", "v3", "v4"]


def test_gappy_response_is_refused_not_padded():
    e = Embedder("http://x", "k", "m")
    e.client = _GappyEndpoint()
    with pytest.raises(ValueError, match="bad indices"):
        e.embed(["A", "B", "C"])


def test_empty_input_returns_empty():
    e = Embedder("http://x", "k", "m")
    e.client = _ShuffledEndpoint()
    assert e.embed([]) == []
