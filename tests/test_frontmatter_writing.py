"""Frontmatter is written from caller input — tags and titles arrive as JSON
from MCP hosts and the console — and used to be spliced in bare.

  a tag with a comma, bracket or newline   broke the whole tag list
  a title with ` #`                        was cut off at the hash (a comment)
  a title with a newline                   ended the frontmatter early, so
  `title: "x\\n---\\ninjected: true"`     wrote a key the caller never sent
  a body starting with "# Heading"         titled the note "# Heading",
                                           which reads back as no title at all

Values are quoted the way YAML needs (plain when plainly safe, single-
quoted when they hold double quotes, double-quoted otherwise) and always
read back as exactly what was stored.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loci import harness, loaders, memories, wiki
from loci.memories import frontmatter_scalar


def _write(tmp_path, **kw):
    return Path(memories.write_memory(str(tmp_path), kw.pop("text", "body text"), **kw))


def _front(path: Path) -> dict:
    return loaders.parse_frontmatter(path.read_text(encoding="utf-8"))[0]


# ---------- the writer ----------
def test_scalar_is_plain_only_when_plaintly_safe():
    assert frontmatter_scalar("Deploy policy") == "Deploy policy"
    assert frontmatter_scalar("部署策略 v2") == "部署策略 v2"
    assert frontmatter_scalar('Say "hi"') == "'Say \"hi\"'"
    assert frontmatter_scalar("it's fine") == '"it\'s fine"'
    assert frontmatter_scalar("Notes on #hashtags") == '"Notes on #hashtags"'
    assert frontmatter_scalar("true") == '"true"'                  # would read as a boolean
    assert frontmatter_scalar("line one\nline two") == "line one line two"   # one line, always; plain once it is


def test_tags_with_punctuation_survive_the_round_trip(tmp_path):
    path = _write(tmp_path, tags=["a, b", "x]", 'say "hi"', "line\nbreak", "plain", 7, None, "  "])
    tags = _front(path)["tags"]
    assert tags == ["memory", "a b", "x]", 'say "hi"', "line break", "plain", "7"]


def test_a_tag_given_as_one_comma_separated_string_is_a_list_of_tags(tmp_path):
    # hosts do not all validate the schema; it used to be iterated per character
    assert _front(_write(tmp_path, tags="rag, memory system"))["tags"] == ["memory", "rag", "memory system"]


TITLES = ['Say "hi"', "Notes on #hashtags", "true", "[draft] plan", "Deploy: policy",
          "line one\nline two", "  spaced  out  ", "it's fine", "部署策略：v2"]


def test_titles_read_back_exactly(tmp_path):
    for i, title in enumerate(TITLES):
        path = _write(tmp_path / f"t{i}", title=title)
        expected = " ".join(title.split())
        assert _front(path)["title"] == expected, title
        assert path.read_text(encoding="utf-8").splitlines()[0] == "---"      # one block only


def test_a_newline_in_a_title_cannot_inject_frontmatter(tmp_path):
    path = _write(tmp_path, title="x\n---\ninjected: true\n---\n")
    meta = _front(path)
    assert set(meta) == {"tags", "created", "title"}
    assert "injected" not in meta
    assert meta["title"] == "x --- injected: true ---"


def test_a_body_that_opens_with_a_heading_titles_the_note_with_that_heading(tmp_path):
    # no explicit title: the first line is used, hashes and all — and
    # `title: # Heading` read back as an empty value (a YAML comment)
    path = _write(tmp_path, text="# Heading\n\nbody")
    assert _front(path)["title"] == "Heading"


def test_caller_json_that_is_not_a_string_is_stored_not_rejected(tmp_path):
    path = _write(tmp_path / "a", text={"decision": "blue-green"}, title=42)
    assert _front(path)["title"] == "42"
    assert "blue-green" in path.read_text(encoding="utf-8")


# ---------- the other two frontmatter writers ----------
def test_wiki_page_topic_is_quoted_and_cannot_inject(tmp_path):
    topic = 'Topic "quoted" #1\n---\ninjected: true\n---\n'
    cfg = SimpleNamespace(wiki={"path": str(tmp_path / "wiki")})
    page = wiki.write_wiki_page(cfg, topic, "body", [])
    meta = _front(page)
    assert "injected" not in meta
    assert meta["topic"] == " ".join(topic.split())


def test_harness_digest_frontmatter_survives_quotes_in_the_icon(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "n.md").write_text("note", encoding="utf-8")

    class Cfg:
        memories = {"path": str(tmp_path / "mem")}
        llm = {"api_key": "k"}

    tool = harness.Harness('my "tool"', "generic", 'x"y', [notes])
    monkeypatch.setattr(harness, "_llm_digest", lambda cfg, bundle: "digest body")

    # index_memory_file is imported inside summarize and best-effort: without an
    # embedder it raises and is swallowed, which is fine for this test
    harness.summarize(Cfg, tool, force=True)
    meta = _front(harness.summary_path(Cfg, tool))
    assert meta["icon"] == 'x"y'
    assert meta["title"] == 'my "tool" memory digest'
    assert meta["harness"] == 'my "tool"'
