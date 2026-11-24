"""Surrounding quotes are removed only as a matching pair.

`str.strip("\"'")` strips whatever quote characters happen to sit at the
two ends, paired or not: a title of `Say "hi"` came back as `Say "hi`
(its closing quote eaten), and `"mismatched'` passed as a quoted value.
YAML unquotes one matching pair and nothing else.
"""
from __future__ import annotations

from types import SimpleNamespace

from loci import governance, loaders, supersede
from loci.http_api import Audit, _make_handler
from loci.mcp_server import Brain


def _meta(body: str) -> dict:
    return loaders.parse_frontmatter("---\n" + body + "---\nbody\n")[0]


def test_a_quote_inside_a_title_is_kept():
    assert _meta('title: Say "hi"\n')["title"] == 'Say "hi"'
    assert _meta("title: it's fine\n")["title"] == "it's fine"


def test_one_matching_pair_is_removed():
    assert _meta('title: "Quoted title"\n')["title"] == "Quoted title"
    assert _meta("title: 'single quoted'\n")["title"] == "single quoted"


def test_a_mismatched_pair_is_not_treated_as_quotes():
    assert _meta('title: "mismatched\'\n')["title"] == "\"mismatched'"


def test_list_values_follow_the_same_rule():
    meta = _meta('tags: ["a", \'b\']\ntitle: [draft]\nlist:\n  - Say "hi"\n')
    assert meta["tags"] == ["a", "b"]
    assert meta["list"] == ['Say "hi"']


def test_console_titles_keep_their_closing_quote(tmp_path):
    (tmp_path / "note.md").write_text(
        "---\ntitle: Say \"hi\"\n---\n# Heading that is not the title\n\nbody\n", encoding="utf-8")
    brain = Brain.__new__(Brain)
    assert brain._file_title(str(tmp_path / "note.md")) == 'Say "hi"'

    cfg = SimpleNamespace(memories={"path": str(tmp_path)},
                          http={"icons": str(tmp_path), "local_admin": False})
    cls = _make_handler(SimpleNamespace(), cfg, [{"token": "t", "role": "admin", "label": "t"}], Audit())
    assert cls.__new__(cls)._list_memories()[0]["title"] == 'Say "hi"'


def test_governance_unquotes_one_pair(tmp_path):
    (tmp_path / "old.md").write_text("---\ntitle: 'old rule'\n---\nbody\n", encoding="utf-8")
    assert governance._title(tmp_path / "old.md") == "old rule"


def test_a_list_valued_supersedes_reference_resolves_to_its_note(tmp_path):
    # `supersedes: [use-staging]` parses as a list; str(list) is "['use-staging']"
    new = tmp_path / "use-prod.md"
    new.write_text("---\nsupersedes: [use-staging]\n---\nbody\n", encoding="utf-8")
    table = supersede.collect([new, tmp_path / "use-staging.md"])
    assert table["use-prod"]["supersedes"] == "use-staging"
    assert table["use-staging"]["superseded_by"] == "use-prod"
