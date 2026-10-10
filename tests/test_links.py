import contextlib
import io

from loci.loaders import extract_wikilinks
from loci.store import Store


def test_extract_wikilinks_basic():
    assert extract_wikilinks("see [[Target Note]] please") == "Target Note"


def test_extract_wikilinks_alias_and_heading_forms():
    body = "[[A|display]] and [[B#Section]] and [[C]]"
    assert extract_wikilinks(body) == "A,B,C"


def test_extract_wikilinks_dedupes_case_insensitive():
    assert extract_wikilinks("[[Note]] [[note]] [[NOTE]]") == "Note"


def test_no_wikilinks_returns_empty():
    assert extract_wikilinks("just a [markdown](link)") == ""


def _store(tmp_path):
    return Store(str(tmp_path / "db"))


def test_link_map_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.upsert_chunks([{"text": "a body", "section": ""}], [[0.0] * 4],
                        "/n/a.md", "h1", tags="", links="b,c")
    store.upsert_chunks([{"text": "b body", "section": ""}], [[0.0] * 4],
                        "/n/b.md", "h2", tags="", links="")
    graph = store.link_map()
    assert graph["/n/a.md"] == "b,c"
    assert graph["/n/b.md"] == ""


def test_cmd_links_prints_outbound_and_inbound(tmp_path, monkeypatch):
    import loci.cli as cli
    store = _store(tmp_path)
    store.upsert_chunks([{"text": "a", "section": ""}], [[0.0] * 4],
                        "/n/alpha.md", "h", links="beta,gamma")
    store.upsert_chunks([{"text": "b", "section": ""}], [[0.0] * 4],
                        "/n/beta.md", "h", links="alpha")

    cfg = type("C", (), {"store": {"path": str(tmp_path / "db")},
                         "embed": {}, "llm": {}})()
    monkeypatch.setattr(cli, "build", lambda c: (None, store))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_links(cfg, "alpha")
    out = buf.getvalue()
    assert "links to:" in out and "-> beta" in out
    assert "linked from:" in out and "<- /n/beta.md" in out


def test_cmd_links_unknown_note(tmp_path, monkeypatch):
    import loci.cli as cli
    store = _store(tmp_path)
    cfg = type("C", (), {"store": {"path": str(tmp_path / "db")}})()
    monkeypatch.setattr(cli, "build", lambda c: (None, store))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_links(cfg, "nope")
    assert "no note matching" in buf.getvalue()
