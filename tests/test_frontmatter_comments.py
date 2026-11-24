"""YAML lets a value carry a trailing comment: `effective: 2026-03-01  # when
it took effect`. loci's frontmatter parsers did not strip it, so the comment
became part of the value — and the format shown in supersede's own module
docstring produced a chain that never matched its target.

Four parsers read frontmatter: the shared one in loaders, governance's own,
and the title regexes behind the console's hit cards and memory list.
"""
from __future__ import annotations

from types import SimpleNamespace

from loci import governance, loaders, supersede
from loci.http_api import Audit, _make_handler
from loci.mcp_server import Brain

# exactly the example in src/loci/supersede.py's docstring
DOCSTRING_EXAMPLE = ("---\nsupersedes: use-staging            # a note stem or a path\n"
                     "effective: 2026-03-01              # when this note took effect\n---\n"
                     "Use staging.\n")


def test_the_documented_supersede_example_parses_cleanly():
    meta, body = loaders.parse_frontmatter(DOCSTRING_EXAMPLE)
    assert meta["supersedes"] == "use-staging"
    assert meta["effective"] == "2026-03-01"
    assert body.strip() == "Use staging."


def test_the_documented_example_produces_a_working_chain(tmp_path):
    (tmp_path / "use-prod.md").write_text(DOCSTRING_EXAMPLE, encoding="utf-8")
    (tmp_path / "use-staging.md").write_text("---\neffective: 2025-01-01\n---\nold\n", encoding="utf-8")
    table = supersede.collect([tmp_path / "use-prod.md", tmp_path / "use-staging.md"])
    assert table["use-prod"]["supersedes"] == "use-staging"
    assert table["use-staging"]["superseded_by"] == "use-prod"      # the reverse link is derived
    assert [e["stem"] for e in supersede.chain(table, "use-staging")] == ["use-staging", "use-prod"]


def test_comments_on_lists_and_scalars_are_dropped():
    meta, _ = loaders.parse_frontmatter(
        "---\n"
        "tags: [policy, rag]   # two tags\n"
        "title: Deploy policy             # still in force\n"
        "alias:\n"
        "  - shipping   # list item comment\n"
        "empty:   # nothing here\n"
        "# a whole-line comment: with a colon in it\n"
        "---\nbody\n")
    assert meta["tags"] == ["policy", "rag"]
    assert meta["title"] == "Deploy policy"
    assert meta["alias"] == ["shipping"]
    assert meta["empty"] == []
    assert not any(k.startswith("#") for k in meta), "a comment line became a key"


def test_a_hash_that_is_not_a_comment_is_kept():
    meta, _ = loaders.parse_frontmatter(
        "---\n"
        "title: C# notes\n"
        "url: https://example.com/docs/#anchor\n"
        "title2: \"Issue #12 fails\"\n"
        "---\n")
    assert meta["title"] == "C# notes"
    assert meta["url"] == "https://example.com/docs/#anchor"
    assert meta["title2"] == "Issue #12 fails"


def test_governance_sees_the_replacement_of_a_commented_reference(tmp_path):
    (tmp_path / "old.md").write_text(
        "---\nsuperseded_by: new-policy       # replaced in March\n---\nold rule\n", encoding="utf-8")
    (tmp_path / "new-policy.md").write_text("# New policy\n\nnew rule\n", encoding="utf-8")

    class Cfg:
        sources = [{"path": str(tmp_path)}]
        governance = {"stale_days": 180}

    findings = governance.scan(Cfg())
    assert len(findings["superseded_live"]) == 1
    assert findings["superseded_live"][0]["superseded_by"] == "new-policy"
    assert findings["superseded_live"][0]["target_exists"] is True     # was False: trailing spaces
    assert findings["dangling"] == []


def _handler(tmp_path):
    cfg = SimpleNamespace(memories={"path": str(tmp_path)},
                          http={"icons": str(tmp_path), "local_admin": False})
    cls = _make_handler(SimpleNamespace(), cfg,
                        [{"token": "t", "role": "admin", "label": "t"}], Audit())
    return cls.__new__(cls)              # the methods need no live request


def test_console_titles_do_not_carry_the_comment(tmp_path):
    (tmp_path / "note.md").write_text(
        "---\ntitle: Nightly backup      # rotate weekly\n---\n# Something else\n\nbody\n",
        encoding="utf-8")
    brain = Brain.__new__(Brain)
    assert brain._file_title(str(tmp_path / "note.md")) == "Nightly backup"
    rows = _handler(tmp_path)._list_memories()
    assert rows[0]["title"] == "Nightly backup"
