"""Embeddings via any OpenAI-compatible endpoint (OpenAI / Zhipu / Ollama / …).
The endpoint must offer /embeddings — chat-only APIs (e.g. DeepSeek) won't
work here; pair them with a separate embedding provider instead."""
from __future__ import annotations

from openai import OpenAI


class Embedder:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def embed(self, texts: list[str], batch: int = 16) -> list[list[float]]:
        """Embed in batches to keep requests within length limits."""
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch):
            part = [t.replace("\n", " ")[:4000] for t in texts[i:i + batch]]
            resp = self.client.embeddings.create(model=self.model, input=part)
            # the response carries the input index of every vector: some
            # OpenAI-compatible endpoints return data out of order (reproduced
            # with a shuffled mock — vectors silently landed on the wrong
            # chunks), so reassemble by index instead of trusting the order
            data = sorted(resp.data, key=lambda d: d.index)
            if [d.index for d in data] != list(range(len(part))):
                raise ValueError(
                    f"embedding endpoint returned bad indices "
                    f"{[d.index for d in data]} for {len(part)} inputs")
            vectors.extend(d.embedding for d in data)
        return vectors
