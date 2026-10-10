from loci.loaders import _read_html, scan_sources


def _write(p, content: str, encoding: str = "utf-8") -> None:
    p.write_bytes(content.encode(encoding))


def test_html_headings_paragraphs_and_list_items(tmp_path):
    f = tmp_path / "page.html"
    _write(f, """<!doctype html>
<html><head><title>Tea Notes</title>
<style>body { color: red }</style></head>
<body>
<script>var x = "noise";</script>
<h2>Spring Harvest</h2>
<p>Longjing before <b>Qingming</b> is worth&nbsp;three times more.</p>
<ul><li>Use 80°C water</li><li>Steep 90 seconds</li></ul>
</body></html>""")
    text = _read_html(f)
    assert text is not None
    lines = text.split("\n\n")
    assert lines[0] == "## Spring Harvest"
    assert "worth three times more." in lines[1]
    assert "- Use 80°C water" in lines
    assert "- Steep 90 seconds" in lines
    assert "noise" not in text          # script skipped
    assert "color: red" not in text     # style skipped


def test_html_title_becomes_h1_when_no_heading(tmp_path):
    f = tmp_path / "noheading.html"
    _write(f, "<html><head><title>Farm Log</title></head>"
              "<body><p>Planted radishes today.</p></body></html>")
    text = _read_html(f)
    assert text is not None
    assert text.startswith("# Farm Log")
    assert "Planted radishes today." in text


def test_html_gb18030_fallback(tmp_path):
    f = tmp_path / "legacy.html"
    _write(f, "<html><body><p>清明前的龙井更贵</p></body></html>", encoding="gb18030")
    text = _read_html(f)
    assert text is not None
    assert "清明前的龙井更贵" in text


def test_html_charset_meta_respected(tmp_path):
    f = tmp_path / "meta.html"
    _write(f, '<html><head><meta charset="gb18030"></head>'
              '<body><p>赶集摆摊</p></body></html>', encoding="gb18030")
    text = _read_html(f)
    assert text is not None
    assert "赶集摆摊" in text


def test_html_markup_only_yields_none(tmp_path):
    f = tmp_path / "empty.html"
    _write(f, "<html><head></head><body><br><hr></body></html>")
    assert _read_html(f) == ""


def test_scan_sources_picks_up_html_and_htm(tmp_path):
    (tmp_path / "a.html").write_text(
        "<html><body><h1>Orders</h1><p>Deliver three radishes.</p></body></html>",
        encoding="utf-8")
    (tmp_path / "b.htm").write_text(
        "<html><body><p>Market opens at noon.</p></body></html>",
        encoding="utf-8")
    docs = scan_sources([{"path": str(tmp_path)}])
    contents = {d["content"] for d in docs}
    assert len(docs) == 2
    assert any("Deliver three radishes." in c for c in contents)
    assert any("Market opens at noon." in c for c in contents)
