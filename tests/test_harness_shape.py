"""One malformed [[harness]] entry must not take every command down.

load_harnesses called h.get() on whatever the config held. A [harness]
section written as one table instead of an array of tables (an easy TOML
slip), a bare string where a table was expected, or a `paths` that is not a
list each raised AttributeError/TypeError — and harness discovery is on the
path of `loci harness`, `loci stats`, serve-http's /harness, /stats and
/source-file, and MCP brain_harness.
"""
from __future__ import annotations

from pathlib import Path

from loci import config, harness


def _cfg(harnesses):
    cfg = config.Config()
    cfg.harnesses = harnesses
    return cfg


def test_a_harness_section_written_as_one_table_is_read_as_one_harness(tmp_path):
    cfg = _cfg({"name": "notes", "type": "generic", "paths": [str(tmp_path)]})
    found = {h.name: h for h in harness.load_harnesses(cfg)}
    assert found["notes"].type == "generic"
    assert found["notes"].roots == [tmp_path.resolve()]


def test_entries_that_are_not_tables_are_skipped_with_a_pointer(tmp_path, capsys):
    cfg = _cfg(["zcode", 42, None, {"name": "configured-ok", "path": str(tmp_path)}])
    found = {h.name: h for h in harness.load_harnesses(cfg)}
    # the good entry still loads (registry harnesses detected on the machine may also be present)
    assert found["configured-ok"].type == "generic"
    assert found["configured-ok"].roots == [tmp_path.resolve()]
    # the bare string "zcode" was NOT read as a config entry: if a zcode
    # harness is present it is the registry one, with the registry preset
    if "zcode" in found:
        assert found["zcode"].type == "zcode"
    assert 42 not in found
    err = capsys.readouterr().err
    assert "skipped" in err and "'zcode'" in err and "42" in err


def test_paths_that_are_not_a_list_yield_no_roots_instead_of_raising(tmp_path):
    for bad in (123, {"a": 1}, True):
        cfg = _cfg([{"name": "x", "type": "generic", "paths": bad}])
        found = {h.name: h for h in harness.load_harnesses(cfg)}
        assert found["x"].roots == []
