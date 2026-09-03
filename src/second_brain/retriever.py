"""检索与问答。"""
from __future__ import annotations

from openai import OpenAI

SYSTEM_PROMPT = (
    "你是用户个人知识库的问答助手。只依据提供的资料回答，"
    "资料里没有的就直说没有，不要编造。回答末尾用 [来源: 文件路径] 列出引用。"
)


class Retriever:
    def __init__(self, embedder, store, top_k: int):
        self.embedder, self.store, self.top_k = embedder, store, top_k

    def search(self, query: str) -> list[dict]:
        vec = self.embedder.embed([query])[0]
        return self.store.query(vec, self.top_k)


def answer(llm_cfg: dict, question: str, hits: list[dict]) -> str:
    context = "\n\n---\n\n".join(
        f"[片段 {i + 1} | 来源: {h['source']}]\n{h['text']}"
        for i, h in enumerate(hits))
    client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
    resp = client.chat.completions.create(
        model=llm_cfg["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"资料：\n\n{context}\n\n---\n\n问题：{question}"},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""
