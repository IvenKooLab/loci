"""Retrieval and question answering."""
from __future__ import annotations

from openai import OpenAI

SYSTEM_PROMPT = (
    "You are a Q&A assistant over the user's personal knowledge base. "
    "Answer only from the provided excerpts; if they don't contain the answer, "
    "say so plainly — do not invent. End your reply with a list of citations "
    "in the form [source: file path]."
)


class Retriever:
    def __init__(self, embedder, store, top_k: int):
        self.embedder, self.store, self.top_k = embedder, store, top_k

    def search(self, query: str) -> list[dict]:
        vec = self.embedder.embed([query])[0]
        return self.store.query(vec, self.top_k)


def answer(llm_cfg: dict, question: str, hits: list[dict]) -> str:
    context = "\n\n---\n\n".join(
        f"[chunk {i + 1} | source: {h['source']}]\n{h['text']}"
        for i, h in enumerate(hits))
    client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
    resp = client.chat.completions.create(
        model=llm_cfg["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""
