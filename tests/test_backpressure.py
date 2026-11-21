"""A 50-thread burst against the live instance froze serve-http to connection
resets. Three fixes pinned here offline: the pipeline lock serializes Brain
work, the server sheds load beyond 16 concurrent handlers (503), and the
whole thing must survive a burst and keep answering."""
from __future__ import annotations

import concurrent.futures
import threading
import urllib.error
import urllib.request

from loci.http_api import Server
from loci.mcp_server import Brain
from conftest import make_cfg, write_corpus


def test_burst_of_ask_survives_and_stays_consistent(tmp_path, monkeypatch):
    b = Brain.__new__(Brain)
    b._cfg = None
    b._retriever = None
    b._store = None
    b._config_error = None
    cfg = make_cfg(tmp_path, write_corpus(tmp_path, {"a.md": "# A\nsensor data"}))
    b._cfg = cfg
    monkeypatch.setattr("loci.retriever.answer",
                        lambda llm, q, h, history=None: "answer text")
    b._ensure()                                # builds a real Retriever+Store

    errors: list[str] = []
    barrier = threading.Barrier(20)

    def worker(i):
        barrier.wait()
        try:
            for _ in range(3):
                out = b.ask(f"sensor question {i}")
                assert isinstance(out, str) and out
        except Exception as e:                    # noqa: BLE001 — the point
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [], errors[:5]


def test_shed_load_beyond_max_concurrent(tmp_path):
    """The server must answer 503 immediately when all handler slots are busy
    instead of queueing thousands of threads."""
    import socket

    srv = Server(("127.0.0.1", 0), None)
    srv.max_concurrent = 2
    srv.gate = threading.BoundedSemaphore(2)

    # occupy all slots as if handlers were running (gate only)
    assert srv.gate.acquire(blocking=False)
    assert srv.gate.acquire(blocking=False)

    # a REAL accepted connection, like the accept loop hands to process_request
    client = socket.socket()
    client.connect(srv.server_address)
    client.settimeout(3)
    conn, _ = srv.socket.accept()
    conn.settimeout(3)

    srv.process_request(conn, client.getsockname())   # must shed, not queue

    data = client.recv(200)
    assert b"503" in data and b"server busy" in data
    srv.gate.release()
