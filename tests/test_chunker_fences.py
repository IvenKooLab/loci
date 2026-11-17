"""Fenced examples keep their text and citation section during ingestion."""
import pytest

from loci.chunker import split_markdown
from conftest import build_index, make_cfg, write_corpus


FENCES = [
    ("```python", "print(1)", "```"),
    ("````markdown", "```python\n# literal heading\n```", "````"),
    ("~~~markdown", "```python\n# literal heading\n```", "~~~"),
    ("~~~~text", "~~~\n# literal heading", "~~~~"),
    ("```text", "```not-a-closing-fence\n# literal heading", "```"),
    ("```text", "    ```\n# literal heading", "```"),
    ("  ````text", "```\n# literal heading", "   `````\t"),
    ("~~~text", "~~~~not-a-closing-fence\n# literal heading", "~~~~"),
]


@pytest.mark.parametrize("size", [80, 10000], ids=["windowed", "whole-block"])
@pytest.mark.parametrize("opening,interior,closing", FENCES)
def test_fence_boundaries_preserve_code_and_citations(size, opening, interior, closing):
    code = opening + "\n" + interior + "\n" + "payload " * 30 + "\n" + closing
    chunks = split_markdown("# Guide\n\n" + code + "\n\n## Next\nfinish", size, 10)
    intact = [c for c in chunks if code.strip() in c["text"]]
    assert len(intact) == 1
    assert intact[0]["section"] == "Guide"
    assert {c["section"] for c in chunks} == {"Guide", "Guide > Next"}
    assert any("finish" in c["text"] and c["section"] == "Guide > Next" for c in chunks)


@pytest.mark.parametrize("opening", ["````markdown", "~~~markdown"])
def test_unclosed_fence_keeps_remaining_headings_as_code(opening):
    code = opening + "\n```\n# literal heading\n" + "payload " * 30
    chunks = split_markdown("# Guide\n\n" + code, 80, 10)
    assert sum(code.strip() in c["text"] for c in chunks) == 1
    assert all(c["section"] == "Guide" for c in chunks)


def test_backticks_in_info_string_are_not_an_opening_fence():
    chunks = split_markdown("# Guide\n```invalid`info\n## Real\nbody", 10000, 10)
    assert [c["section"] for c in chunks] == ["Guide", "Guide > Real"]


@pytest.mark.parametrize("size", [80, 10000])
def test_ingest_persists_complete_example_under_real_section(tmp_path, size):
    code = "````markdown\n```python\n# literal heading\n```\n" + "payload " * 30 + "\n````"
    sources = write_corpus(tmp_path, {"guide.md": "# Guide\n\n" + code + "\n\n## Next\nfinish"})
    cfg = make_cfg(tmp_path, sources)
    cfg.chunk.update(size=size, overlap=10)
    _, store, _ = build_index(cfg)
    records = store.collection.get(include=["documents", "metadatas"])
    intact = [meta for text, meta in zip(records["documents"], records["metadatas"]) if code in text]
    assert len(intact) == 1
    assert intact[0]["section"] == "Guide"
    assert intact[0]["source"].endswith("guide.md")
