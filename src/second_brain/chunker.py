"""切分：markdown 按标题层级切；超长段落滑窗兜底。"""
from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s+", re.M)


def split_markdown(text: str, size: int, overlap: int) -> list[str]:
    """先按标题切段，超长段再按滑窗切。返回切分列表。"""
    sections = _HEADING.split(text)
    # re.split 带捕获组时输出 [前置, 分隔, 内容, 分隔, 内容...]，把标题名拼回内容
    chunks: list[str] = []
    if sections and sections[0].strip():
        chunks.append(sections[0])
    for i in range(1, len(sections) - 1, 2):
        chunks.append(sections[i] + " " + sections[i + 1])

    result: list[str] = []
    for sec in chunks:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= size:
            result.append(sec)
        else:
            result.extend(_sliding_window(sec, size, overlap))
    return [c for c in result if len(c) >= 30]  # 过滤碎片


def _sliding_window(text: str, size: int, overlap: int) -> list[str]:
    step = max(size - overlap, 1)
    return [text[i:i + size] for i in range(0, len(text), step)]
