"""Decision supersession: what replaced what, and when.

From the review thread (Scott Stouffer): a shared memory should answer both
"what should I do now?" and "why did we do it differently last month?" — so a
later exception has to be linkable to the decision it replaced.
"""
from __future__ import annotations

from pathlib import Path

from loci import supersede


def note(root: Path, stem: str, front: str = "", body: str = "body") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{stem}.md"
    p.write_text((f"---\n{front}\n---\n" if front else "") + body, encoding="utf-8")
    return p


def test_forward_pointer_builds_the_chain(tmp_path):
    note(tmp_path, "use-staging", "effective: 2026-01-05")
    note(tmp_path, "staging-exception", "supersedes: use-staging\neffective: 2026-03-01")
    table = supersede.collect(sorted(tmp_path.glob("*.md")))

    line = supersede.chain(table, "use-staging")
    assert [e["stem"] for e in line] == ["use-staging", "staging-exception"]
    assert line[-1]["effective"] == "2026-03-01"


def test_chain_walks_back_to_the_original(tmp_path):
    note(tmp_path, "dec-1", "effective: 2025-11-01")
    note(tmp_path, "dec-2", "supersedes: dec-1\neffective: 2026-01-01")
    note(tmp_path, "dec-3", "supersedes: dec-2\neffective: 2026-04-01")
    table = supersede.collect(sorted(tmp_path.glob("*.md")))

    # asking about the *middle* still yields the whole line
    assert [e["stem"] for e in supersede.chain(table, "dec-2")] == ["dec-1", "dec-2", "dec-3"]
    assert supersede.current_of(table, "dec-1")["stem"] == "dec-3"


def test_backward_pointer_works_without_forward_one(tmp_path):
    note(tmp_path, "old-rule", "superseded_by: new-rule\neffective: 2026-01-01")
    note(tmp_path, "new-rule", "effective: 2026-05-01")
    table = supersede.collect(sorted(tmp_path.glob("*.md")))
    assert [e["stem"] for e in supersede.chain(table, "old-rule")] == ["old-rule", "new-rule"]


def test_wikilink_and_path_values_are_normalized(tmp_path):
    note(tmp_path, "a")
    note(tmp_path, "b", 'supersedes: "[[docs/a]]"')
    note(tmp_path, "c", 'supersedes: "notes/a.md"')
    table = supersede.collect(sorted(tmp_path.glob("*.md")))
    assert table["b"]["supersedes"] == "a"
    assert table["c"]["supersedes"] == "a"


def test_cycles_do_not_loop_forever(tmp_path):
    note(tmp_path, "x", "supersedes: y")
    note(tmp_path, "y", "supersedes: x")
    table = supersede.collect(sorted(tmp_path.glob("*.md")))
    line = supersede.chain(table, "x")          # must terminate
    assert 1 <= len(line) <= 2


def test_notes_without_the_convention_are_ignored(tmp_path):
    note(tmp_path, "plain", "tags: [a]")
    assert supersede.collect(sorted(tmp_path.glob("*.md"))) == {}


def test_describe_marks_the_newest(tmp_path):
    note(tmp_path, "v1", "effective: 2026-01-01")
    note(tmp_path, "v2", "supersedes: v1\neffective: 2026-02-01")
    table = supersede.collect(sorted(tmp_path.glob("*.md")))
    text = supersede.describe(supersede.chain(table, "v1"))
    assert "oldest first" in text
    assert "superseded by" in text               # the arrow between entries
    assert "2026-02-01" in text


def test_annotate_tags_only_superseded_hits(tmp_path):
    note(tmp_path, "stale", "superseded_by: fresh\neffective: 2026-03-01")
    note(tmp_path, "fresh")
    table = supersede.collect(sorted(tmp_path.glob("*.md")))
    hits = [{"source": str(tmp_path / "stale.md")}, {"source": str(tmp_path / "fresh.md")}]
    out = supersede.annotate(hits, table)
    assert out[0]["superseded_by"] == "fresh"
    assert out[0]["effective"] == "2026-03-01"
    assert "superseded_by" not in out[1]
    assert len(out) == 2                          # additive: nothing dropped
