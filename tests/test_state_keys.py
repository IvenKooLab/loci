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


# ---------- records saved before keys folded case ----------
# The old naming kept the key's original case in the file name. On a
# case-sensitive volume (Linux) `Order-42.json` was invisible to a lookup
# spelled `order-42` — and these cases only reproduce there; on Windows and
# macOS the file system already folds case.

def test_a_legacy_spelling_is_found_under_any_case_and_moved_on_save(tmp_path):
    cfg = Cfg(tmp_path)
    legacy = tmp_path / "task" / "Order-42.json"
    legacy.parent.mkdir()
    legacy.write_text('{"v": "old"}', encoding="utf-8")
    spellings = ("Order-42", "order-42", "ORDER-42")
    for spelling in spellings:
        assert state.get(cfg, "task", spelling) == {"v": "old"}, spelling

    state.save(cfg, "task", "Order-42", {"v": "new"})
    for spelling in spellings:
        assert state.get(cfg, "task", spelling) == {"v": "new"}, spelling
    # one record, spelled on disk the way keys are spelled now
    assert [p.name for p in (tmp_path / "task").iterdir()] == ["order-42.json"]
    assert [r["key"] for r in state.list_records(cfg)] == ["order-42"]


def test_two_legacy_spellings_of_one_key_read_newest_and_merge_on_save(tmp_path):
    import os
    cfg = Cfg(tmp_path)
    (tmp_path / "task").mkdir()
    older, newer = tmp_path / "task" / "task-1.json", tmp_path / "task" / "Task-1.json"
    older.write_text('{"v": 1}', encoding="utf-8")
    newer.write_text('{"v": 2}', encoding="utf-8")       # on Windows this overwrites: one file
    for f, t in ((older, 1_000), (newer, 2_000)):
        if f.exists():
            os.utime(f, (t, t))

    assert state.get(cfg, "task", "TASK-1") == {"v": 2}  # last write wins
    state.save(cfg, "task", "task-1", {"v": 3})
    assert state.get(cfg, "task", "Task-1") == {"v": 3}
    left = sorted(p.name for p in (tmp_path / "task").iterdir() if p.suffix == ".json")
    assert left == ["task-1.json"]                      # …and one key is one record


def test_a_legacy_type_directory_spelled_in_another_case_is_found(tmp_path):
    cfg = Cfg(tmp_path)
    (tmp_path / "Task").mkdir()
    (tmp_path / "Task" / "x.json").write_text('{"v": 1}', encoding="utf-8")
    assert state.get(cfg, "task", "x") == {"v": 1}
    assert state.get(cfg, "TASK", "X") == {"v": 1}

    state.save(cfg, "task", "x", {"v": 2})
    assert state.get(cfg, "TASK", "X") == {"v": 2}
    assert [(p.parent.name, p.name) for p in tmp_path.rglob("*.json")] == [("task", "x.json")]


def test_a_truncated_legacy_record_is_kept_not_deleted(tmp_path):
    """Two long keys that shared a truncated legacy file: a save under one
    cannot prove the old file held that key's data, so it is left alone."""
    cfg = Cfg(tmp_path)
    legacy = tmp_path / "task" / (state._slug(LONG + "67890") + ".json")   # the old naming
    legacy.parent.mkdir()
    legacy.write_text('{"v": "legacy"}', encoding="utf-8")

    assert state.get(cfg, "task", LONG + "67890") == {"v": "legacy"}
    state.save(cfg, "task", LONG + "67890", {"v": "new"})
    assert state.get(cfg, "task", LONG + "67890") == {"v": "new"}
    assert legacy.exists()


def test_the_legacy_search_matches_by_folded_name_on_every_platform(tmp_path):
    """Direct test of the search itself: on Windows and macOS the folded
    path already resolves (the volume folds case), so the lookup above
    never reaches the search — on Linux it is the only way a legacy record
    is found under a differently-cased key."""
    cfg = Cfg(tmp_path)
    (tmp_path / "Task").mkdir()                       # type spelled with a capital
    a = tmp_path / "Task" / "Order-42.json"           # …and so is the key
    a.write_text('{"v": 1}', encoding="utf-8")
    assert state._legacy_files(cfg, "task", "order-42") == [a]
    assert state._legacy_files(cfg, "TASK", "ORDER-42") == [a]
    assert state._legacy_files(cfg, "task", "order-43") == []
    assert state._legacy_files(cfg, "other", "order-42") == []
    assert state._legacy_files(Cfg(tmp_path / "missing"), "task", "x") == []
