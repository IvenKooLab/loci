"""Quality baseline and index export writes must survive concurrency.

`quality.pin` wrote its baseline with a bare write_text (a torn file reads
as {} and every later compare screams drift), and store.export staged a
WHARED .part name — two concurrent exports of one target interleaved in
the same staging file, the exact race the state/graph/wiki tmp fix
covered."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_concurrent_pins_leave_a_valid_baseline(tmp_path):
    from loci import quality

    class Cfg:
        store = {"path": str(tmp_path / "chroma")}
        http = {"query_log": ""}            # no log file: snapshot runs on zeros
    cfg = Cfg()
    errors: list[str] = []

    def w(i):
        try:
            for _ in range(10):
                quality._write_baseline(cfg, {"writer": i})
        except Exception as e:                  # noqa: BLE001 — the point
            errors.append(f"{type(e).__name__}: {e}")

    def pin(i):
        try:
            for _ in range(5):
                quality.pin(cfg, window=3)
        except Exception as e:                  # noqa: BLE001 — the point
            errors.append(f"{type(e).__name__}: {e}")

    ts = [threading.Thread(target=pin, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == [], errors[:3]
    snap = json.loads(quality.baseline_path(cfg).read_text(encoding="utf-8"))
    assert isinstance(snap, dict) and "queries" in snap
    leftovers = [p for p in quality.baseline_path(cfg).parent.iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []
