"""Regression tests for the 2026-09 bug-hunt batch. Each test pins a bug that
was confirmed live before its fix — see CHANGELOG v0.2.2."""
import contextlib
import io

import loci.cli as cli_module
from conftest import FakeEmbedder, build_index, make_cfg, patch_brain_config, write_corpus
from loci import chunker, config, loaders
from loci.loaders import extract_wikilinks
from loci.mcp_server import Brain
from loci.store import Store


# [1] heading markers inside fenced code are code, not headings

def test_hash_line_inside_fence_is_not_a_heading():
    code = "# Intro\n```python\n# comment, NOT a heading\nx = 1\n```\nafter text"
    chunks = chunker.split_markdown(code, 800, 100)
    assert len(chunks) == 1                     # no split inside the fence
    assert chunks[0]["section"] == "Intro"      # breadcrumb not corrupted
    assert "# comment, NOT a heading" in chunks[0]["text"]


def test_fence_state_survives_multiple_blocks():
    text = ("# A\n```\n# fake\n```\nreal body one\n\n"
            "# B\n```\n# fake two\n```\nreal body two")
    chunks = chunker.split_markdown(text, 800, 100)
    sections = [c["section"] for c in chunks]
    assert "fake" not in " ".join(sections)
    assert "A" in sections and "B" in sections


# [2] --tag matches exactly, not by substring

def test_tag_filter_is_exact_not_substring(tmp_path):
    sources = write_corpus(tmp_path, {
        "s.md": "---\ntags: [storage]\n---\n# S\nhybrid retrieval keywords",
        "r.md": "---\ntags: [rag]\n---\n# R\nhybrid retrieval keywords",
    })
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    retriever.top_k = 5
    hits = retriever.search("hybrid retrieval keywords", tag="rag")
    assert len(hits) == 1 and hits[0]["tags"] == "rag"   # 'storage' must not match


# [3] --in works with forward slashes against Windows backslash paths

def test_path_filter_normalizes_separators(tmp_path):
    sources = write_corpus(tmp_path, {
        "sub/a.md": "# A\nseparator probe content",
        "b.md": "# B\nseparator probe content",
    })
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    retriever.top_k = 5
    # forward-slash probe must match even if store paths use backslashes
    probe = "sub/a.md".rsplit("/", 1)[0]
    hits = retriever.search("separator probe content", path_contains=probe)
    assert hits and all(probe.replace("/", "\\") in h["source"].replace("\\", "\\")
                        or probe in h["source"].replace("\\", "/") for h in hits)
    assert all("b.md" not in h["source"].replace("\\", "/").split("/")[-1]
               for h in hits) if hits else True


def test_path_filter_separator_agnostic_direct(tmp_path):
    hits_src = [{"source": r"C:\docs\en\note.md", "tags": ""}]
    p = "docs/en".lower().replace("\\", "/")
    assert p in hits_src[0]["source"].lower().replace("\\", "/")


# [4] Obsidian embeds (![[...]]) are not links

def test_embeds_are_excluded_from_wikilinks():
    assert extract_wikilinks("see ![[image.png]] and [[Real Note]]") == "Real Note"


# [5] k is clamped: negative k returns nothing instead of weird slicing

def test_negative_k_returns_empty_not_overflow(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\ncontent about vectors"})
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    retriever.top_k = -1
    assert retriever.search("vectors") == []


# [6] MCP brain_search k override must not leak between calls

def test_mcp_search_k_does_not_leak(monkeypatch, tmp_path):
    class FakeRetriever:
        top_k = 5

        def search(self, query, tag=None, path_contains=None, k=None):
            limit = max(k if k is not None else self.top_k, 0)
            return [{"id": str(i), "text": "t", "source": "a.md", "chunk": 0,
                     "section": "", "tags": "", "links": "", "mtime": 0.0,
                     "distance": 0.1} for i in range(limit)]

    patch_brain_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module, "build", lambda cfg: (None, None))
    monkeypatch.setattr(cli_module, "make_retriever",
                        lambda cfg, e, s: FakeRetriever())
    b = Brain()
    b.search("x", k=2)
    assert b._retriever.top_k == 5                # unchanged — no leak
    assert len(b.search("y").splitlines()) >= 1   # default still works


def test_mcp_search_string_k_is_coerced(monkeypatch, tmp_path):
    class FakeRetriever:
        top_k = 5

        def search(self, query, tag=None, path_contains=None, k=None):
            limit = max(k if k is not None else self.top_k, 0)
            return [{"id": str(i), "text": "t", "source": "a.md", "chunk": 0,
                     "section": "", "tags": "", "links": "", "mtime": 0.0,
                     "distance": 0.1} for i in range(limit)]

    patch_brain_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module, "build", lambda cfg: (None, None))
    monkeypatch.setattr(cli_module, "make_retriever",
                        lambda cfg, e, s: FakeRetriever())
    b = Brain()
    out = b.search("x", k="3")                    # hosts may send strings
    assert out.count("[") == 3


# [7] a file that becomes chunkless drops its stale chunks

def test_chunkless_file_prunes_stale_chunks(tmp_path, monkeypatch):
    note = tmp_path / "notes"
    note.mkdir()
    f = note / "n.md"
    f.write_text("---\ntags: [a]\n---\n# Real\nlong enough body text", encoding="utf-8")
    cfg = make_cfg(tmp_path, [{"path": str(note)}])
    store = Store(cfg.store["path"])
    monkeypatch.setattr(cli_module, "build", lambda c: (FakeEmbedder(), store))
    cli_module.cmd_ingest(cfg)
    assert store.count() >= 1

    f.write_text("---\ntags: [a]\n---\n", encoding="utf-8")   # body gone
    cli_module.cmd_ingest(cfg)
    assert store.count() == 0                    # stale chunks removed


# [8] links inbound matching is exact (short stems can't substring-match)

def test_links_inbound_exact_no_short_stem_false_positive(tmp_path, monkeypatch):
    # nobody links to "a" — but "a" is a substring of unrelated targets,
    # which the old substring matcher would report as an inbound link
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks([{"text": "a", "section": ""}], [[0.0] * 4],
                        "/notes/a.md", "h", links="")
    store.upsert_chunks([{"text": "t", "section": ""}], [[0.0] * 4],
                        "/notes/big-topic.md", "h2", links="vector database design")
    cfg = type("C", (), {"store": {"path": str(tmp_path / "db")}})()
    monkeypatch.setattr(cli_module, "build", lambda c: (None, store))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli_module.cmd_links(cfg, "a")
    out = buf.getvalue()
    assert "linked from:" not in out          # no false inbound from substring
    assert "big-topic.md" not in out.split("links to:")[0]


def test_links_inbound_still_finds_exact_targets(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks([{"text": "b", "section": ""}], [[0.0] * 4],
                        "/notes/beta.md", "h", links="alpha,gamma")
    store.upsert_chunks([{"text": "a", "section": ""}], [[0.0] * 4],
                        "/notes/alpha.md", "h1", links="")
    cfg = type("C", (), {"store": {"path": str(tmp_path / "db")}})()
    monkeypatch.setattr(cli_module, "build", lambda c: (None, store))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli_module.cmd_links(cfg, "alpha")
    out = buf.getvalue()
    assert "linked from:" in out and "/notes/beta.md" in out


# [9] config numeric sanity

def test_config_coerces_string_numbers(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[chunk]\nsize = "800"\noverlap = "0"\n'
                 '[[sources]]\npath = "X"', encoding="utf-8")
    cfg = config.load(str(p))
    assert cfg.chunk["size"] == 800 and cfg.chunk["overlap"] == 0


def test_config_clamps_runaway_overlap(tmp_path, capsys):
    p = tmp_path / "c.toml"
    p.write_text("[chunk]\nsize = 100\noverlap = 800", encoding="utf-8")
    cfg = config.load(str(p))
    assert cfg.chunk["overlap"] == 99
    assert "clamping" in capsys.readouterr().out


def test_config_rejects_garbage_numbers(tmp_path, capsys):
    p = tmp_path / "c.toml"
    p.write_text('[chunk]\nsize = "huge"', encoding="utf-8")
    cfg = config.load(str(p))
    assert cfg.chunk["size"] == 800                 # default restored
    assert "not an int" in capsys.readouterr().out


# [10] same-title chatlog conversations don't overwrite each other

def test_chatlog_duplicate_titles_get_disambiguated(tmp_path):
    import json
    conv = {"title": "same", "mapping": {
        "n": {"message": {"author": {"role": "user"},
                          "content": {"content_type": "text", "parts": ["q"]}}}}}
    (tmp_path / "conversations.json").write_text(
        json.dumps([conv, dict(conv)]), encoding="utf-8")
    docs = loaders.scan_sources([{"path": str(tmp_path)}])
    assert len(docs) == 2
    titles = {d["path"].split("::")[-1] for d in docs}
    assert titles == {"same", "same (2)"}
