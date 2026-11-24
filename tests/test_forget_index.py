"""brain_forget promises the forgotten notes' chunks "leave the index
immediately". They never did: the chunks are keyed by a note's ORIGINAL path,
and the delete was issued for the .trash destination instead — so a retracted
fact stayed searchable until the next full ingest pruned it."""
from __future__ import annotations

import threading
from pathlib import Path

from conftest import make_cfg
from loci.mcp_server import Brain
from loci.store import Store


def test_forget_drops_the_chunks_of_the_forgotten_notes(tmp_path):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "token.md").write_text("the deployment token rotates monthly", encoding="utf-8")
    (mem / "lunch.md").write_text("an unrelated note about lunch", encoding="utf-8")
    cfg = make_cfg(tmp_path, [])
    cfg.memories["path"] = str(mem)
    store = Store(cfg.store["path"])
    for name in ("token.md", "lunch.md"):
        store.upsert_chunks([{"text": name, "section": ""}], [[0.1, 0.2, 0.3]],
                            str((mem / name).resolve()), "h")

    brain = Brain.__new__(Brain)              # no config/network in __init__
    brain._cfg, brain._store = cfg, store
    brain._lock = threading.RLock()
    reply = brain._forget_locked("deployment")

    assert "forgot" in reply
    assert {Path(s).name for s in store.list_sources()} == {"lunch.md"}
    assert (mem / ".trash" / "token.md").is_file()       # soft delete, recoverable
    assert not (mem / "token.md").exists()
