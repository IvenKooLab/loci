"""向量化：OpenAI 兼容 embeddings 端点（智谱/DeepSeek/OpenAI 均适用）。"""
from __future__ import annotations

from openai import OpenAI


class Embedder:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def embed(self, texts: list[str], batch: int = 16) -> list[list[float]]:
        """批量向量化；自动分批避免超长请求。"""
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch):
            part = [t.replace("\n", " ")[:4000] for t in texts[i:i + batch]]
            resp = self.client.embeddings.create(model=self.model, input=part)
            vectors.extend(d.embedding for d in resp.data)
        return vectors
