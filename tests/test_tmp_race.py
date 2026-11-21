"""Three write paths staged their atomic replace through a SHARED tmp name
(`path.with_suffix(...tmp)`): two agents saving the same task/key at once
stomped each other's staging file and 7/8 writes died FileNotFoundError.
The tmp name is now unique per writer (pid + thread id)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_concurrent_state_saves_same_key_all_succeed(tmp_path):
    from loci import state

    class Cfg:
        state = {"path": str(tmp_path / "state")}
    cfg = Cfg()
    errors: list[str] = []

    def worker(i):
        try:
            for n in range(10):
                state.save(cfg, "task", "8f3c", {"writer": i, "n": n})
        except Exception as e:                    # noqa: BLE001 — the point
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [], errors[:3]
    data = state.get(cfg, "task", "8f3c")
    assert data and data["writer"] in range(8)    # complete JSON, last write wins
    leftovers = list((tmp_path / "state").rglob("*.tmp"))
    assert leftovers == []                        # staging files all replaced


def test_concurrent_graph_saves_all_succeed(tmp_path, monkeypatch):
    from loci import graph

    monkeypatch.setattr(graph, "_extract_triples", lambda c, t: [])
    class Cfg:
        store = {"path": str(tmp_path / "chroma")}
        memories = {"path": str(tmp_path / "memories")}
        wiki = {"path": str(tmp_path / "wiki")}
        llm = {"api_key": "", "base_url": "x", "model": "m"}
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "n.md").write_text("note", encoding="utf-8")
    cfg = Cfg()
    errors: list[str] = []

    def worker():
        try:
            for _ in range(5):
                graph.save_graph(cfg, {"version": 1, "processed": {}, "entities": {}, "edges": []})
        except Exception as e:                    # noqa: BLE001 — the point
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [], errors[:3]
