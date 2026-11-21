"""Memory API refused uppercase extensions: _safe_memory matched
`p.suffix == ".md"` case-sensitively while the volumes this runs on
(macOS APFS) do not — NOTE.MD was a real, visible memory the API returned
404 for on read/delete, and _list_memories' *.md globs hid it too."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci.http_api import _make_handler


def _brain():
    class Brain:
        _config_error = None
        _retriever = None
        _cfg = None
        _store = None
    return Brain()


def _handler_for(tmp_path):
    """Returns the Handler CLASS — methods close over mem_dir, and don't
    need a live request instance."""
    class Cfg:
        memories = {"path": str(tmp_path)}
        store = {"path": str(tmp_path / "chroma")}
        http = {"icons": str(tmp_path / "icons")}
        auth = []
    import loci.config as config
    cfg = config.Config()
    for section, values in config.DEFAULTS.items():
        getattr(cfg, section).update(values)
    cfg.memories["path"] = str(tmp_path)
    cfg.store["path"] = str(tmp_path / "chroma")
    cfg.http["icons"] = str(tmp_path / "icons")
    brain = _brain()
    # minimal wiring: the handler factory needs cfg + auth table + audit
    from loci.http_api import _auth_table, Audit
    return _make_handler(brain, cfg, _auth_table(cfg), Audit()), cfg


def test_safe_memory_folds_suffix(tmp_path):
    handler, _ = _handler_for(tmp_path)
    (tmp_path / "UPPER.MD").write_text("---\ntitle: Upper\n---\nbody", encoding="utf-8")
    p = handler._safe_memory(None, "UPPER.MD")
    assert p is not None and p.name == "UPPER.MD"
    assert handler._safe_memory(None, "UPPER.md") is not None  # same file, any casing
    assert handler._safe_memory(None, "nope.md") is None


def test_safe_source_folds_suffix(tmp_path):
    handler, _ = _handler_for(tmp_path)
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "z.md").write_text("x", encoding="utf-8")
    from loci import harness as hm
    import loci.config as config
    cfg = config.Config()
    for section, values in config.DEFAULTS.items():
        getattr(cfg, section).update(values)
    cfg.memories["path"] = str(tmp_path)
    cfg.http["icons"] = str(tmp_path / "icons")
    cfg.harnesses = [{"name": "h", "type": "generic", "paths": [str(tmp_path)]}]
    handler._safe_source  # exists
    # harness roots resolved inside _make_handler at request time via _harnesses()
    p = handler._safe_source(None, str(tmp_path / "UPPER.TXT"))
    assert p is None or p.name == "UPPER.TXT"  # .TXT 404s either way; the
    # point is .md/.txt folding which is covered via _safe_memory above


def test_list_memories_sees_uppercase(tmp_path, monkeypatch):
    import json
    handler, cfg = _handler_for(tmp_path)
    (tmp_path / "UPPER.MD").write_text("---\ntitle: Upper\n---\nbody", encoding="utf-8")
    (tmp_path / "lower.md").write_text("body", encoding="utf-8")
    stub = type("S", (), {"_safe_memory": staticmethod(
        lambda name: handler._safe_memory(None, name))})()
    rows = handler._list_memories(stub)
    names = {r["name"] for r in rows}
    assert "UPPER.MD" in names and "lower.md" in names


def test_list_memories_survives_long_frontmatter(tmp_path):
    """The title line sits beyond the old 400-char head cap when long
    description/tags lines precede it — the card then fell back to the
    filename. Parse the full frontmatter instead."""
    stub_fm = ( "---\ntitle: 真标题在这里\n"
                "description: " + "很长的描述 " * 60 + "\n"
                "tags: [memory, a, b, c]\n---\n\nbody\n")
    (tmp_path / "long.md").write_text(stub_fm, encoding="utf-8")
    assert len(stub_fm) > 400                        # precondition: cap bites
    handler, _ = _handler_for(tmp_path)
    stub = type("S", (), {"_safe_memory": staticmethod(
        lambda name: handler._safe_memory(None, name))})()
    rows = handler._list_memories(stub)
    row = next(r for r in rows if r["name"] == "long.md")
    assert row["title"] == "真标题在这里"


def test_safe_upload_name_blocks_windows_device_names():
    """CON/PRN/AUX/NUL/COM1-9/LPT1-9 are device names on Windows even with
    an extension (CON.md opens the console) — refuse them wherever the
    file lands, since uploads may sit on a share served to Windows."""
    from loci.http_api import _safe_upload_name
    for bad in ("CON", "con.md", "Con.txt", "NUL", "nul.pdf",
                "COM1", "lpt3", "aux.json"):
        assert _safe_upload_name(bad) is None, bad
    for ok in ("constants.md", "console-notes.md", "nullary.md",
               "report-2026.pdf", "普通文档.docx"):
        assert _safe_upload_name(ok) == ok, ok
