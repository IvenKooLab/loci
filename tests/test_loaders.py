from loci.loaders import file_hash, parse_frontmatter, scan_sources, tags_of


def test_file_hash_is_stable():
    assert file_hash("abc") == file_hash("abc")
    assert file_hash("abc") != file_hash("abd")


def test_frontmatter_list_tags():
    meta, body = parse_frontmatter("---\ntags:\n  - rag\n  - notes\n---\nbody text")
    assert meta["tags"] == ["rag", "notes"]
    assert body == "body text"


def test_frontmatter_inline_tags_and_scalars():
    meta, body = parse_frontmatter(
        '---\ntags: [a, "b c"]\nalias: note1\n---\nrest')
    assert meta["tags"] == ["a", "b c"]
    assert meta["alias"] == "note1"
    assert body == "rest"


def test_no_frontmatter_returns_body_intact():
    meta, body = parse_frontmatter("just text\n---\nnot frontmatter")
    assert meta == {}
    assert body.startswith("just text")


def test_unclosed_frontmatter_left_untouched():
    raw = "---\ntags: [x]\nno closing fence"
    meta, body = parse_frontmatter(raw)
    assert meta == {}
    assert body == raw


def test_tags_of_normalizes_list_and_string():
    assert tags_of({"tags": ["a", "b"]}) == "a,b"
    assert tags_of({"tags": "a, b ,c"}) == "a,b,c"
    assert tags_of({}) == ""


def test_scan_sources_reads_md_and_txt(tmp_path):
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")
    docs = scan_sources([{"path": str(tmp_path)}])
    assert {d["content"] for d in docs} == {"hello", "world"}


def test_scan_sources_skips_missing_dir(tmp_path, capsys):
    docs = scan_sources([{"path": str(tmp_path / "nope")}])
    assert docs == []
    assert "not found" in capsys.readouterr().out


def test_scan_sources_skips_non_utf8(tmp_path, capsys):
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    assert scan_sources([{"path": str(tmp_path)}]) == []
    assert "UTF-8" in capsys.readouterr().out


def test_scan_sources_dedupes_overlapping_roots(tmp_path):
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    docs = scan_sources([{"path": str(tmp_path)}, {"path": str(tmp_path)}])
    assert len(docs) == 1


def test_scan_sources_peels_frontmatter_into_tags(tmp_path):
    (tmp_path / "n.md").write_text("---\ntags: [rag]\n---\nbody", encoding="utf-8")
    docs = scan_sources([{"path": str(tmp_path)}])
    assert docs[0]["tags"] == "rag"
    assert docs[0]["content"] == "body"
