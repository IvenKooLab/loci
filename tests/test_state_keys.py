"""An exact-key store must never let two keys share a record.

`_slug` alone let them: anything past 80 characters was cut off (two long
ids with the same prefix mapped to one file — the second save silently
replaced the first), and on case-insensitive volumes (Windows, default
macOS) `Task-1` and `task-1` are one name. Keys now fold to one case on
every platform and a too-long key ends in a digest of its full form.
"""
from __future__ import annotations

from loci import state


class Cfg:
    def __init__(self, root):
        self.state = {"path": str(root)}


LONG = "https://api.example.com/v2/orders/2026/11/region/cn-north-1/customer-12345/invoice/"


def test_long_keys_that_share_a_prefix_stay_distinct(tmp_path):
    cfg = Cfg(tmp_path)
    state.save(cfg, "task", LONG + "67890", {"v": 1})
    state.save(cfg, "task", LONG + "99999", {"v": 2})
    assert state.get(cfg, "task", LONG + "67890") == {"v": 1}
    assert state.get(cfg, "task", LONG + "99999") == {"v": 2}
    assert len(state.list_records(cfg)) == 2
    assert state.delete(cfg, "task", LONG + "67890") is True
    assert state.get(cfg, "task", LONG + "99999") == {"v": 2}


def test_keys_differing_only_by_case_are_one_key_everywhere(tmp_path):
    cfg = Cfg(tmp_path)
    state.save(cfg, "task", "Task-1", {"v": "first"})
    assert state.get(cfg, "task", "task-1") == {"v": "first"}
    state.save(cfg, "task", "TASK-1", {"v": "second"})
    assert state.get(cfg, "task", "Task-1") == {"v": "second"}
    assert len(state.list_records(cfg)) == 1


def test_records_saved_under_the_old_naming_are_found_and_moved(tmp_path):
    cfg = Cfg(tmp_path)
    legacy = tmp_path / "task" / "Order-42.json"
    legacy.parent.mkdir()
    legacy.write_text('{"v": "old"}', encoding="utf-8")

    assert state.get(cfg, "task", "Order-42") == {"v": "old"}
    assert state.get(cfg, "task", "order-42") == {"v": "old"}

    state.save(cfg, "task", "Order-42", {"v": "new"})
    assert state.get(cfg, "task", "order-42") == {"v": "new"}
    assert len(state.list_records(cfg)) == 1
    assert state.delete(cfg, "task", "order-42") is True
    assert state.get(cfg, "task", "Order-42") is None


def test_a_type_prefix_matches_case_insensitively(tmp_path):
    cfg = Cfg(tmp_path)
    state.save(cfg, "Order", "1", {"v": 1})
    state.save(cfg, "task", "1", {"v": 2})
    assert [r["type"] for r in state.list_records(cfg, "ORDER")] == ["order"]
