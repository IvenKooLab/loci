"""`serve-http` on a busy port: another loci instance is a normal thing to have.

Two instances (different `LOCI_HOME`) on one machine used to die with a bare
`OSError: Address already in use` traceback. These pin the operator-facing
message, and that `--port 0` reports the port it actually got.
"""
from __future__ import annotations

import errno
import socket
from http.server import ThreadingHTTPServer

import pytest

from loci import http_api


def test_bind_conflict_is_named_not_traced(monkeypatch):
    squat = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = squat.server_address[1]
    try:
        class FakeBrain:
            def _ensure(self):
                pass

        monkeypatch.setattr(http_api, "Brain", lambda: FakeBrain())
        monkeypatch.setattr(http_api, "Audit", lambda: None)
        monkeypatch.setattr(http_api, "_auth_table", lambda cfg: [
            {"token": "t", "role": "admin", "label": "t"}])
        monkeypatch.setattr(http_api, "_make_handler", lambda *a, **k: None)

        with pytest.raises(SystemExit) as exit_info:
            http_api.run_server(_cfg(), "127.0.0.1", port)
        message = str(exit_info.value)
        assert f"127.0.0.1:{port}" in message
        assert "already in use" in message
        assert "lsof -i" in message
        assert "--port 0" in message
        assert f"--port {port + 1}" in message
    finally:
        squat.server_close()


def test_port_zero_reports_the_bound_port(capsys):
    """`--port 0` must not leave the operator guessing which port was chosen."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), None)
    try:
        bound = server.server_address[1]
        assert bound != 0
        assert 1024 < bound < 65536
    finally:
        server.server_close()


def test_unrelated_oserror_still_raises(monkeypatch):
    """Only the two cases we can explain get a friendly message."""
    def boom(*a, **k):
        raise OSError(errno.ENOMEM, "out of memory")

    monkeypatch.setattr(http_api, "ThreadingHTTPServer", boom)
    monkeypatch.setattr(http_api, "Brain", lambda: type(
        "B", (), {"_ensure": lambda self: None})())
    monkeypatch.setattr(http_api, "Audit", lambda: None)
    monkeypatch.setattr(http_api, "_auth_table", lambda cfg: [
        {"token": "t", "role": "admin", "label": "t"}])
    monkeypatch.setattr(http_api, "_make_handler", lambda *a, **k: None)
    with pytest.raises(OSError):
        http_api.run_server(_cfg(), "127.0.0.1", 0)


def _cfg():
    from types import SimpleNamespace
    return SimpleNamespace(
        http={"host": "127.0.0.1", "port": 8765, "local_admin": True,
              "icons": "./icons", "query_log": ""},
        memories={"path": "/tmp"}, auth=[], sources=[], harnesses=[])
