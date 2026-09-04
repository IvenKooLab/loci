from second_brain.chunker import split_markdown


def test_empty_text_returns_no_chunks():
    assert split_markdown("", 800, 100) == []
    assert split_markdown("   \n  \n", 800, 100) == []


def test_heading_creates_chunks_with_breadcrumbs():
    text = "# Alpha\nbody one\n\n## Beta\nbody two\n\n### Gamma\nbody three"
    chunks = split_markdown(text, 800, 100)
    sections = [c["section"] for c in chunks]
    assert sections == ["Alpha", "Alpha > Beta", "Alpha > Beta > Gamma"]
    assert all("body" in c["text"] for c in chunks)


def test_heading_line_stays_in_its_chunk():
    chunks = split_markdown("# Title\ncontent here", 800, 100)
    assert len(chunks) == 1
    assert chunks[0]["text"].startswith("# Title")
    assert "content here" in chunks[0]["text"]


def test_text_before_first_heading_has_empty_section():
    chunks = split_markdown("lead paragraph\n\n# After\nbody", 800, 100)
    assert chunks[0]["section"] == ""
    assert chunks[1]["section"] == "After"


def test_oversized_prose_falls_back_to_sliding_window():
    prose = "word " * 400  # ~2000 chars
    chunks = split_markdown("# Big\n" + prose, size=800, overlap=100)
    assert len(chunks) > 1
    assert all(c["section"] == "Big" for c in chunks)
    assert all(len(c["text"]) <= 800 for c in chunks)
    # overlap: consecutive windows share content
    assert chunks[0]["text"][-40:] in chunks[1]["text"]


def test_fenced_code_block_is_never_split():
    code = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(200)) + "\n```"
    assert len(code) > 800  # would be windowed if treated as prose
    chunks = split_markdown("# Code\n" + code, size=800, overlap=100)
    code_chunks = [c for c in chunks if c["text"].startswith("```python")]
    assert len(code_chunks) == 1  # whole block survives as one chunk
    assert code_chunks[0]["text"].endswith("```")


def test_unclosed_fence_treated_as_code():
    """A block within size stays whole — heading plus (unclosed) code together."""
    text = "# X\n```js\nconst a = 1;\nconst b = 2;"
    chunks = split_markdown(text, 800, 100)
    assert len(chunks) == 1
    assert "```js" in chunks[0]["text"]
    assert chunks[0]["text"].rstrip().endswith("const b = 2;")


def test_prose_around_code_becomes_separate_chunks():
    filler = "prose sentence with enough words to bulk up the block. " * 12
    text = "# Mix\n" + filler + "\n```\ncode\n```\n" + filler + "tail"
    chunks = split_markdown(text, 800, 100)
    assert len(chunks) == 3
    assert any(c["text"].startswith("```") for c in chunks)
    assert any(c["text"].startswith("# Mix") for c in chunks)
    assert chunks[-1]["text"].endswith("tail")


def test_short_natural_blocks_survive():
    """Tiny but real notes must stay searchable (no silent dropping)."""
    chunks = split_markdown("# Quick note\nlunch at 3", 800, 100)
    assert len(chunks) == 1
    assert chunks[0]["section"] == "Quick note"


def test_tiny_tail_window_is_merged_not_dropped():
    body = "sentence word " * 120  # ~1680 chars of prose
    chunks = split_markdown("# Big\n" + body, size=800, overlap=100)
    assert len(chunks) >= 2
    assert all(len(c["text"]) >= 30 for c in chunks)


def test_whitespace_only_file_yields_nothing():
    assert split_markdown("   \n\t\n  \n", 800, 100) == []


def test_heading_only_note_stays_searchable():
    """A one-line note is real content — never silently dropped."""
    chunks = split_markdown("# AWS billing setup", 800, 100)
    assert len(chunks) == 1
    assert chunks[0]["section"] == "AWS billing setup"


def test_chinese_content_survives_splitting():
    text = "# 标题\n" + "这是一段足够长的中文内容，用来测试切分。" * 40
    chunks = split_markdown(text, 300, 50)
    assert len(chunks) > 1
    assert all(c["section"] == "标题" for c in chunks)
