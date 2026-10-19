"""Harness memory hub: type presets, fingerprint gating, summary writing."""
import json

import pytest

from loci import harness as hm
from loci.store import Store


def make_cfg(tmp_path, entries):
    class Cfg: pass
    cfg = Cfg()
    cfg.harnesses = entries
    cfg.memories = {"path": str(tmp_path / "memories")}
    cfg.llm = {"base_url": "http://x", "api_key": "k", "model": "m"}
    cfg.chunk = {"size": 800, "overlap": 100}
    cfg.http = {"icons": str(tmp_path / "icons")}
    return cfg


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture(autouse=True)
def _registry_off(monkeypatch):
    """Tests are machine-independent: default to an empty discovery registry;
    discovery tests install their own specs."""
    monkeypatch.setattr(hm, "KNOWN_HARNESSES", {})


def test_discovery_probes_and_env_expansion(tmp_path, monkeypatch):
    home = tmp_path / "zhome"
    home.mkdir()
    monkeypatch.setattr(hm, "KNOWN_HARNESSES", {
        "zcode": {"display": "ZCode", "type": "zcode", "emoji": "⚡",
                  "icons": ["zcode.png"], "probe": ["~/.zzzcode-does-not-exist"],
                  "memory": []},
        "dsh": {"display": "DeepSeek Harness", "type": "generic", "emoji": "🐳",
                "icons": [], "probe": ["$MY_DSH"],
                "memory": ["$MY_DSH"]},
    })
    monkeypatch.setenv("MY_DSH", str(tmp_path / "dsh-data"))
    (tmp_path / "dsh-data").mkdir()
    cfg = make_cfg(tmp_path, [])
    cfg.http = {"icons": str(tmp_path / "icons")}

    found = {h.name: h for h in hm.load_harnesses(cfg)}
    assert "zcode" not in found                    # probe missed
    assert found["dsh"].display == "DeepSeek Harness"
    assert found["dsh"].roots == [tmp_path / "dsh-data"]  # $ENV expanded
    assert found["dsh"].icon == "🐳"               # no icon files installed


def test_discovery_icon_candidate_from_icons_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(hm, "KNOWN_HARNESSES", {
        "zcode": {"display": "ZCode", "type": "zcode", "emoji": "⚡",
                  "icons": ["zcode.png"], "probe": [str(tmp_path)],
                  "memory": []},
    })
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "zcode.png").write_bytes(b"png")
    cfg = make_cfg(tmp_path, [])
    cfg.http = {"icons": str(tmp_path / "icons")}
    (h,) = hm.load_harnesses(cfg)
    assert h.icon == "zcode.png"


def test_config_entry_overrides_discovered(tmp_path, monkeypatch):
    monkeypatch.setattr(hm, "KNOWN_HARNESSES", {
        "zcode": {"display": "ZCode", "type": "zcode", "emoji": "⚡",
                  "icons": [], "probe": [str(tmp_path)],
                  "memory": []},
    })
    cfg = make_cfg(tmp_path, [{"name": "zcode", "type": "generic",
                               "paths": [str(tmp_path / "custom")],
                               "icon": "🚀"}])
    cfg.http = {"icons": str(tmp_path / "icons")}
    (h,) = hm.load_harnesses(cfg)
    assert h.type == "generic" and h.icon == "🚀"
    assert h.roots == [tmp_path / "custom"]        # config wins over registry


def test_zcode_preset_finds_project_memories(tmp_path):
    root = tmp_path / "memories"
    _write(root / "projects/a/memory/x.md", "a")
    _write(root / "projects/b/memory/y.md", "b")
    _write(root / "stray.md", "not matched")     # not under projects/*/memory
    h = hm.Harness("zcode", "zcode", "⚡", [root])
    names = {p.name for p in hm.memory_files(h)}
    assert names == {"x.md", "y.md"}


def test_codex_preset_is_flat(tmp_path):
    root = tmp_path / "codex"
    _write(root / "MEMORY.md", "i")
    _write(root / "note.md", "n")
    _write(root / "sub/deep.md", "d")            # subdirs are not codex memories
    h = hm.Harness("codex", "codex", "🐙", [root])
    assert {p.name for p in hm.memory_files(h)} == {"MEMORY.md", "note.md"}


def test_generic_recursive_and_fallback(tmp_path):
    root = tmp_path / "generic"
    _write(root / "a/b/c.md", "deep")
    h = hm.Harness("ekko", "generic", "🦜", [root])
    assert [p.name for p in hm.memory_files(h)] == ["c.md"]
    # a zcode root with no projects/* still yields files via the fallback
    h2 = hm.Harness("flat", "zcode", "⚡", [root])
    assert [p.name for p in hm.memory_files(h2)] == ["c.md"]


def test_fingerprint_changes_with_content(tmp_path):
    p = tmp_path / "m.md"
    p.write_text("v1", encoding="utf-8")
    h = hm.Harness("x", "generic", "🗂️", [tmp_path])
    f1 = hm.fingerprint(hm.memory_files(h))
    p.write_text("v2", encoding="utf-8")
    assert hm.fingerprint(hm.memory_files(h)) != f1


class FakeLLM:
    calls = 0
    @staticmethod
    def digest(llm_cfg, bundle):                 # same arity as hm._llm_digest
        FakeLLM.calls += 1
        return f"digest of {len(bundle)} chars"


@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setattr(hm, "_llm_digest", FakeLLM.digest)
    FakeLLM.calls = 0                           # class-level counter: reset per test
    return FakeLLM


def test_summarize_writes_gated_note(tmp_path, fake_llm):
    root = tmp_path / "mem"
    _write(root / "a.md", "hello memory " * 10)
    cfg = make_cfg(tmp_path, [{"name": "t", "type": "generic",
                               "paths": [str(root)]}])
    h = hm.load_harnesses(cfg)[0]

    r1 = hm.summarize(cfg, h)
    assert r1["status"] == "written" and fake_llm.calls == 1
    note = hm.summary_path(cfg, h).read_text(encoding="utf-8")
    assert "fingerprint:" in note and "tags: [memory, harness, summary]" in note

    r2 = hm.summarize(cfg, h)                    # unchanged: gated, zero LLM
    assert r2["status"] == "unchanged" and fake_llm.calls == 1

    root.joinpath("a.md").write_text("changed!", encoding="utf-8")
    r3 = hm.summarize(cfg, h)
    assert r3["status"] == "written" and fake_llm.calls == 2

    r4 = hm.summarize(cfg, h, force=True)        # forced: calls again
    assert r4["status"] == "written" and fake_llm.calls == 3


def test_summarize_empty_harness_is_reported(tmp_path, fake_llm):
    cfg = make_cfg(tmp_path, [{"name": "void", "type": "generic",
                               "paths": [str(tmp_path / "nothing")]}])
    r = hm.summarize(cfg, hm.load_harnesses(cfg)[0])
    assert r["status"] == "empty" and fake_llm.calls == 0


def test_stats_counts_chunks_under_roots(tmp_path):
    root = tmp_path / "mem"
    f = root / "a.md"
    _write(f, "# A\n" + "content " * 50)
    cfg = make_cfg(tmp_path, [{"name": "t", "type": "generic",
                               "paths": [str(root)]}])
    store = Store(str(tmp_path / "chroma"))
    store.upsert_chunks([{"text": "c", "section": ""}], [[0.1] * 4],
                        str(f), "hash1")
    store.upsert_chunks([{"text": "other", "section": ""}], [[0.2] * 4],
                        str(tmp_path / "elsewhere.md"), "hash2")
    rows = hm.stats(cfg, store, hm.load_harnesses(cfg))
    assert rows[0]["files"] == 1 and rows[0]["chunks"] == 1
    assert rows[0]["summary"]["status"] == "missing"


def test_stats_table_renders_and_hints_config(tmp_path):
    assert "[[harness]]" in hm.stats_table([])
    row = {"name": "z", "type": "zcode", "icon": "⚡", "files": 3, "chunks": 9,
           "last_updated": "2026-10-17 12:00",
           "summary": {"status": "fresh", "path": "/x"}}
    assert "z" in hm.stats_table([row]) and "fresh" in hm.stats_table([row])
