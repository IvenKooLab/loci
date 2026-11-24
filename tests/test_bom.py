"""Notes saved with a UTF-8 BOM are valid UTF-8 and must read like any other.

Windows editors write one by default — Windows PowerShell 5's Out-File,
older Notepad, plenty of Chinese editors — and every reader opened files
as plain "utf-8", which keeps U+FEFF as the first character. Everything
that looks at the START of a file then missed:

  frontmatter    not recognized: tags lost, the yaml leaked into the body
                 and was indexed as a chunk of its own
  first heading  not a heading: its text fell into the unnamed section
  supersession   a `supersedes:` chain starting at byte 0 read as absent
  console titles the frontmatter title was not found

config.toml with a BOM was worse: tomllib rejects it, so loci refused to
start at all.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from conftest import FakeEmbedder
from loci import chunker, config, governance, loaders, memories, supersede
from loci.mcp_server import Brain
from loci.store import Store

NOTE = ("---\ntags: [policy, rag]\ntitle: Deployment policy, v2\n---\n"
        "# Deploy policy\n\nUse blue-green.\n\n## Rollback\nCall ops.\n")


def _bom(text: str) -> bytes:
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def test_scan_sources_reads_frontmatter_and_the_first_heading(tmp_path):
    (tmp_path / "note.md").write_bytes(_bom(NOTE))
    docs = loaders.scan_sources([{"path": str(tmp_path)}])

    assert docs[0]["tags"] == "policy,rag"          # was "" — frontmatter unseen
    sections = [c["section"] for c in chunker.split_markdown(docs[0]["content"], 800, 100)]
    assert sections[0] == "Deploy policy"            # was "" — heading unseen behind the BOM
    assert "tags:" not in docs[0]["content"]         # the yaml was leaking into the body
    assert "\ufeff" not in docs[0]["content"]


def test_the_same_note_without_a_bom_reads_identically(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "note.md").write_text(NOTE, encoding="utf-8")
    bom = tmp_path / "bom"
    bom.mkdir()
    (bom / "note.md").write_bytes(_bom(NOTE))
    a = loaders.scan_sources([{"path": str(plain)}])[0]
    b = loaders.scan_sources([{"path": str(bom)}])[0]
    assert (a["content"], a["tags"], a["hash"]) == (b["content"], b["tags"], b["hash"])


def test_index_memory_file_keeps_the_tags(tmp_path, monkeypatch):
    import loci.cli as cli
    from conftest import make_cfg
    cfg = make_cfg(tmp_path, [])
    mem = tmp_path / "mem"
    mem.mkdir()
    path = mem / "note.md"
    path.write_bytes(_bom(NOTE))
    monkeypatch.setattr(cli, "build", lambda cfg: (FakeEmbedder(), Store(cfg.store["path"])))

    assert memories.index_memory_file(cfg, str(path)) > 0
    tags = Store(cfg.store["path"]).collection.get(include=["metadatas"])["metadatas"][0]["tags"]
    assert tags == "policy,rag"


def test_supersession_and_governance_see_a_chain_that_starts_at_byte_0(tmp_path):
    (tmp_path / "new.md").write_bytes(_bom("---\nsupersedes: use-staging\neffective: 2026-03-01\n---\nbody\n"))
    (tmp_path / "use-staging.md").write_text("---\neffective: 2025-01-01\n---\nold\n", encoding="utf-8")
    files = [tmp_path / "new.md", tmp_path / "use-staging.md"]

    table = supersede.collect(files)
    assert table["new"]["supersedes"] == "use-staging"          # was ""
    assert table["use-staging"]["superseded_by"] == "new"

    meta = governance._frontmatter(tmp_path / "new.md")
    assert meta["supersedes"] == "use-staging"                   # was {}


def test_console_title_comes_from_the_frontmatter(tmp_path):
    (tmp_path / "note.md").write_bytes(_bom(NOTE))
    brain = Brain.__new__(Brain)
    # the frontmatter title, not the heading it would fall back to
    assert brain._file_title(str(tmp_path / "note.md")) == "Deployment policy, v2"


def test_html_page_with_a_bom_has_no_stray_character(tmp_path):
    (tmp_path / "page.html").write_bytes(_bom(
        '<html><head><meta charset="utf-8"><title>T</title></head><body><h1>Head</h1><p>Body</p></body></html>'))
    text = loaders._read_text(tmp_path / "page.html")
    assert text.startswith("# Head")
    assert "\ufeff" not in text


def test_config_toml_with_a_bom_loads(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_bytes(_bom('[chunk]\nsize = 500\n[llm]\nmodel = "m"\n'))
    monkeypatch.setenv("LOCI_HOME", str(tmp_path))
    cfg = config.load()                       # used to raise TOMLDecodeError at startup
    assert cfg.chunk["size"] == 500 and cfg.llm["model"] == "m"
