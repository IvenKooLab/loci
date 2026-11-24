"""A request that announces a body and never sends it must not hold a worker
slot forever.

serve-http sheds load past `max_concurrent` handlers (a 503), which assumes
slots come back. The handler had no socket timeout, so a connection that
sent `Content-Length` and then stalled — a crashed upload, a laptop that
slept mid-request, anyone on loopback — blocked in rfile.read() for good.
Sixteen of them and the whole server answered 503 until it was restarted.
"""
from __future__ import annotations

import socket
import threading
import time
from types import SimpleNamespace

import pytest

import loci.http_api as http_api
from loci.http_api import Audit, _make_handler


def _get_status(port: int) -> int:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        data = b""
        while b"\r\n" not in data:
            chunk = s.recv(200)
            if not chunk:
                break
            data += chunk
    return int(data.split(b" ")[1]) if data.startswith(b"HTTP/") else 0


@pytest.fixture
def one_slot_server(tmp_path, monkeypatch):
    cfg = SimpleNamespace(memories={"path": str(tmp_path / "mem")},
                          http={"icons": str(tmp_path), "local_admin": False})
    monkeypatch.setattr("loci.harness.load_harnesses", lambda _: [])
    handler = _make_handler(SimpleNamespace(), cfg,
                            [{"token": "t", "role": "admin", "label": "t"}], Audit())
    monkeypatch.setattr(handler, "timeout", 0.5)                  # the shipped value is 60 s
    monkeypatch.setattr(http_api.Server, "max_concurrent", 1)     # makes the slot visible
    server = http_api.Server(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server, handler
    finally:
        server.shutdown()
        server.server_close()


def test_the_shipped_handler_has_a_socket_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("loci.harness.load_harnesses", lambda _: [])
    cfg = SimpleNamespace(memories={"path": str(tmp_path / "mem")},
                          http={"icons": str(tmp_path)})
    handler = _make_handler(SimpleNamespace(), cfg,
                            [{"token": "t", "role": "admin", "label": "t"}], Audit())
    assert handler.timeout and handler.timeout >= 30, \
        "no socket timeout: a stalled peer holds its worker slot forever"


def test_a_stalled_body_gives_its_slot_back(one_slot_server):
    server, handler = one_slot_server
    port = server.server_address[1]

    stall = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        stall.sendall(b"POST /search HTTP/1.1\r\nHost: x\r\nContent-Length: 500\r\n\r\n{")
        time.sleep(0.2)
        assert _get_status(port) == 503                  # the one slot is taken

        deadline = time.time() + 8                       # …and comes back by itself
        status = None
        while time.time() < deadline:
            status = _get_status(port)
            if status == 401:                            # healthy again (no credentials sent)
                break
            time.sleep(0.2)
        assert status == 401, f"slot still held after {handler.timeout}s: last status {status}"

        reply = stall.recv(200)                          # the stalled client is told, not left hanging
        assert b" 408 " in reply
    finally:
        stall.close()


def test_an_idle_connection_does_not_hold_its_slot(one_slot_server):
    server, _ = one_slot_server
    port = server.server_address[1]
    idle = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        idle.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n")     # headers never finished
        time.sleep(0.2)
        assert _get_status(port) == 503
        deadline = time.time() + 8
        while time.time() < deadline and _get_status(port) != 401:
            time.sleep(0.2)
        assert _get_status(port) == 401
    finally:
        idle.close()
