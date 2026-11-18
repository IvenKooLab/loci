"""Exact-key structured state: the task-state complement to semantic memory.

File-based on purpose (hand-editable, no DB), so these tests run anywhere —
no ChromaDB needed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from loci import state


class FakeCfg:
    def __init__(self, root: Path):
        self.state = {"path": str(root / "state")}
        self.store = {"path": str(root / "chroma_db")}
        self.memories = {"path": str(root / "memories")}


def test_save_then_get_round_trips_verbatim(tmp_path):
    cfg = FakeCfg(tmp_path)
    payload = {"stage": "underwriting", "slots": {"plan": "重疾险"}, "n": 3}
    state.save(cfg, "task", "t-8f3c", payload)
    assert state.get(cfg, "task", "t-8f3c") == payload   # byte-faithful, no envelope


def test_get_missing_key_returns_none_not_error(tmp_path):
    cfg = FakeCfg(tmp_path)
    assert state.get(cfg, "task", "nope") is None


def test_save_overwrites_last_write_wins(tmp_path):
    cfg = FakeCfg(tmp_path)
    state.save(cfg, "task", "k", {"v": 1})
    state.save(cfg, "task", "k", {"v": 2})
    assert state.get(cfg, "task", "k") == {"v": 2}


def test_types_are_namespaces_not_searches(tmp_path):
    """task/x and order/x are different records — no cross-type bleed."""
    cfg = FakeCfg(tmp_path)
    state.save(cfg, "task", "shared", {"a": 1})
    state.save(cfg, "order", "shared", {"b": 2})
    assert state.get(cfg, "task", "shared") == {"a": 1}
    assert state.get(cfg, "order", "shared") == {"b": 2}


def test_keys_are_slugged_filesystem_safe(tmp_path):
    cfg = FakeCfg(tmp_path)
    state.save(cfg, "cus tomer", "../escape/attempt", {"ok": True})
    # hostile input lands inside the state dir, not outside it
    root = Path(cfg.state["path"]).resolve()
    for f in root.rglob("*.json"):
        assert f.resolve().is_relative_to(root)
    assert state.get(cfg, "cus tomer", "../escape/attempt") == {"ok": True}


def test_list_newest_first_and_prefix_filter(tmp_path):
    cfg = FakeCfg(tmp_path)
    state.save(cfg, "task", "a", {"i": 1})
    state.save(cfg, "task", "b", {"i": 2})
    state.save(cfg, "order", "c", {"i": 3})
    # three saves inside one file-clock tick carry identical mtimes on
    # Windows, which used to leave the order to glob enumeration — pin
    # strictly increasing mtimes so this tests the newest-first semantics.
    base = 1_700_000_000
    for i, (type_, key) in enumerate((("task", "a"), ("task", "b"), ("order", "c"))):
        os.utime(state._record_path(cfg, type_, key), (base + i, base + i))
    rows = state.list_records(cfg)
    assert [r["key"] for r in rows] == ["c", "b", "a"]      # newest first
    only_orders = state.list_records(cfg, "order")
    assert [r["key"] for r in only_orders] == ["c"]
    assert {r["type"] for r in only_orders} == {"order"}


def test_tied_mtimes_list_deterministically(tmp_path):
    cfg = FakeCfg(tmp_path)
    for type_, key in (("task", "b"), ("order", "z"), ("task", "a")):
        state.save(cfg, type_, key, {"i": 0})
    # everything in one tick: order must be stable (type, then key), not the
    # directory-enumeration accident it used to be
    for path in (state_dir := state.state_dir(cfg)).glob("*/*.json"):
        os.utime(path, (1_700_000_000, 1_700_000_000))
    rows = state.list_records(cfg)
    assert [(r["type"], r["key"]) for r in rows] == \
        [("order", "z"), ("task", "a"), ("task", "b")]


def test_delete_is_exact(tmp_path):
    cfg = FakeCfg(tmp_path)
    state.save(cfg, "task", "gone", {"x": 1})
    state.save(cfg, "task", "kept", {"x": 2})
    assert state.delete(cfg, "task", "gone") is True
    assert state.delete(cfg, "task", "gone") is False        # second time: absent
    assert state.get(cfg, "task", "kept") == {"x": 2}


def test_oversized_record_is_rejected_not_truncated(tmp_path):
    """Silent truncation would corrupt task state; refuse instead."""
    cfg = FakeCfg(tmp_path)
    big = {"blob": "x" * (state.MAX_RECORD_BYTES + 10)}
    with pytest.raises(ValueError):
        state.save(cfg, "task", "big", big)
    assert state.get(cfg, "task", "big") is None


def test_non_object_data_is_rejected(tmp_path):
    cfg = FakeCfg(tmp_path)
    with pytest.raises(ValueError):
        state.save(cfg, "task", "str", "not-a-json-object")


def test_corrupt_record_reads_as_absent(tmp_path):
    """A hand-edit gone wrong must not crash every get/list."""
    cfg = FakeCfg(tmp_path)
    state.save(cfg, "task", "ok", {"a": 1})
    bad = Path(cfg.state["path"]) / "task" / "broken.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json", encoding="utf-8")
    assert state.get(cfg, "task", "broken") is None
    keys = {r["key"] for r in state.list_records(cfg)}
    assert keys == {"ok", "broken"}                          # listed, readable
