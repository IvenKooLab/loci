"""Retrieval-quality improvements: per-document diversity cap and the
strict grounding system prompt."""
from collections import Counter

from conftest import build_index, make_cfg, write_corpus


# [1] diversity cap: one document can't crowd out the whole result list

def test_diversify_caps_chunks_per_document():
    from loci.retriever import Retriever
    r = Retriever(None, None, top_k=5, max_per_doc=2)
    hits = [{"id": str(i), "source": "a.md"} for i in range(4)] + \
           [{"id": "b1", "source": "b.md"}, {"id": "c1", "source": "c.md"}]
    out = r._diversify(hits, 5)
    sources = [h["source"] for h in out]
    assert sources.count("a.md") == 2          # surplus a.md chunks dropped
    assert "b.md" in sources and "c.md" in sources   # slots freed for others


def test_diversify_zero_disables_cap():
    from loci.retriever import Retriever
    r = Retriever(None, None, top_k=5, max_per_doc=0)
    hits = [{"id": str(i), "source": "a.md"} for i in range(4)]
    assert len(r._diversify(hits, 4)) == 4     # 0 = keep the original behavior


def test_diversify_preserves_ranking_order():
    from loci.retriever import Retriever
    r = Retriever(None, None, top_k=5, max_per_doc=2)
    hits = [{"id": "a1", "source": "a.md"}, {"id": "b1", "source": "b.md"},
            {"id": "a2", "source": "a.md"}, {"id": "a3", "source": "a.md"}]
    out = r._diversify(hits, 5)
    assert [h["id"] for h in out] == ["a1", "b1", "a2"]


def test_search_applies_diversity_cap(tmp_path):
    sources = write_corpus(tmp_path, {
        "a.md": "# A\n" + "\n\n".join(f"向量检索段落{i} 内容" for i in range(6)),
        "b.md": "# B\n向量检索的另一篇文档段落",
    })
    sources[0]["chunk_size"] = 20             # force a.md into many chunks
    sources[0]["chunk_overlap"] = 0
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    retriever.top_k = 5
    hits = retriever.search("向量检索")
    counts = Counter(h["source"].replace("\\", "/").split("/")[-1] for h in hits)
    assert counts["a.md"] <= 2                 # cap holds end-to-end
    assert counts.get("b.md", 0) >= 1          # the other doc gets a slot


# [2] system prompt: strict grounding rules

def test_system_prompt_forbids_fabrication():
    from loci.retriever import SYSTEM_PROMPT
    assert "do not invent" in SYSTEM_PROMPT
    assert "Never use outside knowledge" in SYSTEM_PROMPT


def test_system_prompt_requires_explicit_unknown_answer():
    from loci.retriever import SYSTEM_PROMPT
    assert "知识库中没有相关信息" in SYSTEM_PROMPT


def test_system_prompt_mandates_citations():
    from loci.retriever import SYSTEM_PROMPT
    assert "Sources:" in SYSTEM_PROMPT
    assert "[source: file path > section]" in SYSTEM_PROMPT
