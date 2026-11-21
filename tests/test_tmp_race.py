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


def test_concurrent_readers_and_writers_on_windows(tmp_path):
    """On Windows, Path.replace over a file another thread is READING fails
    with WinError 5 (no FILE_SHARE_DELETE) — and the reader's open() fails
    the same instant. A reader/writer mix on one key used to raise out of
    state.save; the writer now backs off and retries while the collision
    lasts, and reads tolerate the same instant via their OSError guard."""
    from loci import state

    class Cfg:
        state = {"path": str(tmp_path / "state")}
    cfg = Cfg()
    state.save(cfg, "task", "8f3c", {"v": 0})
    errors: list[str] = []
    reads = {"ok": 0}

    def reader():
        while not stop.is_set():
            try:
                if state.get(cfg, "task", "8f3c") is not None:
                    reads["ok"] += 1
            except OSError as e:               # the guard must make this unreachable
                errors.append(f"read {type(e).__name__}: {e}")

    def writer(i):
        try:
            for n in range(40):
                state.save(cfg, "task", "8f3c", {"writer": i, "n": n})
        except Exception as e:                 # noqa: BLE001 — the point
            errors.append(f"write {type(e).__name__}: {e}")

    stop = threading.Event()
    r1 = threading.Thread(target=reader)
    r1.start()
    ws = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    [t.start() for t in ws]
    [t.join() for t in ws]
    stop.set()
    r1.join()
    assert errors == [], errors[:3]
    assert reads["ok"] > 0


def test_concurrent_write_memory_all_succeed(tmp_path):
    """write_memory staged through a SHARED path.with_suffix('.md.tmp') — the
    fourth copy of the same race (state/graph/wiki were fixed earlier): 8
    agents remembering at once stomped each other's staging file. Also, an
    empty body used to die on splitlines()[0] before anything hit disk."""
    from loci import memories

    errors: list[str] = []

    def worker(i):
        try:
            for n in range(10):
                p = memories.write_memory(
                    str(tmp_path / "mem"),
                    f"note from {i}/{n}" if (i + n) % 7 else "",   # 1 in 7: blank body
                    title=None if (i + n) % 7 else "blank-body-note")
                assert Path(p).exists()
        except Exception as e:                  # noqa: BLE001 — the point
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [], errors[:3]
    written = list((tmp_path / "mem").glob("*.md"))
    assert len(written) == 80                   # every write landed, none lost
    leftovers = list((tmp_path / "mem").glob("*.tmp"))
    assert leftovers == []                      # staging files all replaced
