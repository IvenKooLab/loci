import second_brain.cli as cli_module
from conftest import FakeEmbedder, write_corpus
from second_brain import config
from second_brain.store import Store
from second_brain.watcher import ingest_once


def make_cfg(tmp_path):
    sources = write_corpus(tmp_path, {"a.md": "# A\nwatch me change"})
    cfg = config.Config()
    for section, values in config.DEFAULTS.items():
        getattr(cfg, section).update(values)
    cfg.sources = sources
    cfg.store["path"] = str(tmp_path / "chroma")
    return cfg


def patch_offline_pipeline(monkeypatch, tmp_path):
    store = Store(str(tmp_path / "chroma"))
    monkeypatch.setattr(cli_module, "build",
                        lambda cfg: (FakeEmbedder(), store))
    return store


def test_first_pass_indexes_second_skips(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    store = patch_offline_pipeline(monkeypatch, tmp_path)
    assert ingest_once(cfg) == 1
    assert store.count() > 0
    assert ingest_once(cfg) == 0  # unchanged: nothing re-embedded


def test_change_triggers_reindex_and_delete_prunes(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    store = patch_offline_pipeline(monkeypatch, tmp_path)
    ingest_once(cfg)
    before = store.count()

    note = tmp_path / "notes" / "a.md"
    note.write_text("# A\nwatch me change — now different", encoding="utf-8")
    assert ingest_once(cfg) == 1
    assert store.count() == before  # replaced, not duplicated

    note.unlink()
    assert ingest_once(cfg) == 0
    assert store.list_sources() == set()  # pruned
    assert store.count() == 0
