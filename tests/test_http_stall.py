"""A request that announces a body and never sends it must not hold a worker
slot forever.

serve-http sheds load past `max_concurrent` handlers (a 503), which assumes
slots come back. The handler had no socket timeout, so a connection that
sent `Content-Length` and then stalled — a crashed upload, a laptop that
slept mid-request, anyone on loopback — blocked in rfile.read() for good.
Sixteen of them and the whole server answered 503 until it was restarted.
"""
from __future__ import annotations

import select
import socket
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import loci.http_api as http_api
from loci.http_api import Audit, _make_handler

HEALTHY = 401          # /health without credentials

# The two timing tests below probe the server while it is shedding. On the
# Windows loopback a shed connection is reset by the OS (it is closed with
# the request unread), and in roughly one run in five a handler serving a
# later probe then sat in sendall until the stalled client closed — an
# artifact of the probe traffic, not of the timeout under test: in every
# such run the 408 still arrived at 0.51 s and the stalled handler had
# ended. The timeout itself is pinned everywhere by the test above.
unreliable_on_windows_loopback = pytest.mark.skipif(
    sys.platform == "win32",
    reason="shed-connection resets on the Windows loopback make the probe timing unreliable")


def _probe(port: int):
    """The status /health answers with, or None when the server shed the
    connection. A shed connection is closed with the request unread, which
    the OS turns into a reset rather than a clean close — so "no reply" and
    "503" both mean the slot was taken."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            data = b""
            while b"\r\n" not in data:
                chunk = s.recv(200)
                if not chunk:
                    break
                data += chunk
    except OSError:
        return None
    return int(data.split(b" ")[1]) if data.startswith(b"HTTP/") else None


def _slot_taken(port: int) -> bool:
    return _probe(port) != HEALTHY


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


def _wait_readable(sock: socket.socket, seconds: float) -> bool:
    readable, _, _ = select.select([sock], [], [], seconds)
    return bool(readable)


def test_the_shipped_handler_has_a_socket_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("loci.harness.load_harnesses", lambda _: [])
    cfg = SimpleNamespace(memories={"path": str(tmp_path / "mem")},
                          http={"icons": str(tmp_path)})
    handler = _make_handler(SimpleNamespace(), cfg,
                            [{"token": "t", "role": "admin", "label": "t"}], Audit())
    assert handler.timeout and handler.timeout >= 30, \
        "no socket timeout: a stalled peer holds its worker slot forever"


@unreliable_on_windows_loopback
def test_a_stalled_body_is_answered_and_gives_its_slot_back(one_slot_server):
    server, handler = one_slot_server
    port = server.server_address[1]

    stall = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        stall.sendall(b"POST /search HTTP/1.1\r\nHost: x\r\nContent-Length: 500\r\n\r\n{")
        time.sleep(0.3)
        assert _slot_taken(port), "the stalled request should be holding the only slot"

        # the server gives up on the body and says so, instead of waiting forever
        assert _wait_readable(stall, 10), \
            f"no answer after 10s: the body read did not time out (Handler.timeout={handler.timeout})"
        reply = stall.recv(200)
        assert b" 408 " in reply

        deadline = time.time() + 5                   # …and the slot comes back with it
        while time.time() < deadline and _slot_taken(port):
            time.sleep(0.1)
        assert not _slot_taken(port), "slot still held after the stalled body was answered"
    finally:
        stall.close()


@unreliable_on_windows_loopback
def test_an_idle_connection_does_not_hold_its_slot(one_slot_server):
    server, _ = one_slot_server
    port = server.server_address[1]
    idle = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        idle.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n")     # headers never finished
        time.sleep(0.3)
        assert _slot_taken(port)

        deadline = time.time() + 5
        while time.time() < deadline and _slot_taken(port):
            time.sleep(0.1)
        assert not _slot_taken(port)
    finally:
        idle.close()
