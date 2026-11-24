"""graph.json is documented as human-readable and hand-editable.

Every reader trusted its shape. A hand edit that dropped a top-level key
(processed / edges / entities), left the file half written, or turned it
into something other than an object raised KeyError / TypeError out of all
of them: `loci graph show`, `loci graph build`, brain_graph, and the wiki
page context.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from loci import graph


class Cfg:
    def __init__(self, root):
        self.store = {"path": str(root)}
        self.llm = {"api_key": ""}
        self.memories = {"path": str(root / "m")}
        self.wiki = {"path": str(root / "w")}


def _write(root, data):
    (root / "graph.json").write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return Cfg(root)


EDGE = {"s": "T8", "p": "speeds_up", "o": "drafts", "source": "notes.md", "ts": 1}


def test_a_graph_missing_top_level_keys_still_answers(tmp_path):
    cfg = _write(tmp_path, {"version": 1, "edges": [EDGE]})       # no processed, no entities
    result = graph.query_graph(cfg, "t8")
    assert [e["o"] for e in result["out"]] == ["drafts"]
    assert graph.query_graph(cfg, "")["hubs"] == []                 # nothing indexed, nothing claimed
    summary = graph.build_graph(cfg, dirs=[])                       # rebuild from nothing
    assert summary["edges"] == 1


def test_edges_missing_a_side_are_skipped_not_fatal(tmp_path):
    cfg = _write(tmp_path, {"edges": [EDGE, {"s": "A"}, "junk", {"s": "B", "p": "uses", "o": 5}]})
    assert [e["s"] for e in graph.query_graph(cfg, "a")["out"]] == []


def test_a_file_that_is_not_an_object_reads_as_an_empty_graph(tmp_path):
    for data in ("[1, 2]", "null", '"text"', "{not json", ""):
        result = graph.query_graph(_write(tmp_path, data), "anything")
        assert result["out"] == [] and result["in"] == [] and result["hubs"] == []
    summary = graph.build_graph(_write(tmp_path, "[]"), dirs=[])
    assert summary == {"files": 0, "new": 0, "edges": 0, "entities": 0}


def test_entity_entries_that_are_not_records_do_not_break_the_hub_list(tmp_path):
    cfg = _write(tmp_path, {"entities": {"A": {"degree": 3, "sources": []}, "B": "junk", "C": {}}})
    assert [h["name"] for h in graph.query_graph(cfg, "")["hubs"]] == ["A"]


def test_the_empty_default_is_not_shared_between_calls(tmp_path):
    a = graph.load_graph(Cfg(tmp_path))
    a["edges"].append(EDGE)
    a["processed"]["x.md"] = "h"
    b = graph.load_graph(Cfg(tmp_path))
    assert b["edges"] == [] and b["processed"] == {}
