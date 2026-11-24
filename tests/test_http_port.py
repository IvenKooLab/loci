"""`serve-http` on a busy port: another loci instance is a normal thing to have.

Two instances (different `LOCI_HOME`) on one machine used to die with a bare
`OSError: Address already in use` traceback. These pin the operator-facing
message, and that `--port 0` reports the port it actually got.

On Windows the squat server holds the port with SO_REUSEADDR while loci's
`Server` binds without it (see http_api.Server) — without that asymmetry the
second bind silently *succeeds* on Windows and `serve_forever` hangs the test.
"""
from __future__ import annotations

import errno
import socket
import sys
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
        if sys.platform == "win32":
            assert "netstat -ano" in message
        else:
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

    monkeypatch.setattr(http_api, "Server", boom)
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


# ---- `--port 0`: the escape hatch the bind-conflict message recommends ----

def _fake_brain(monkeypatch, server_cls):
    bound = {}
    monkeypatch.setattr(http_api, "Server", server_cls(bound))
    monkeypatch.setattr(http_api, "Brain", lambda: type(
        "B", (), {"_ensure": lambda self: None})())
    monkeypatch.setattr(http_api, "Audit", lambda: None)
    monkeypatch.setattr(http_api, "_auth_table", lambda cfg: [
        {"token": "t", "role": "admin", "label": "t"}])
    monkeypatch.setattr(http_api, "_make_handler", lambda *a, **k: None)
    return bound


def test_cli_port_zero_is_honoured_not_replaced_by_the_configured_port():
    """`--port 0` asks the OS for a free port. `args.port or <config>` is
    falsy for 0, so the flag was silently replaced by the configured port —
    the very port that was already taken."""
    from types import SimpleNamespace
    from loci import cli
    cfg = SimpleNamespace(http={"port": 18765})
    assert cli.resolve_port(0, cfg) == 0
    assert cli.resolve_port(None, cfg) == 18765       # no flag: the configured port
    assert cli.resolve_port(9000, cfg) == 9000


@pytest.mark.parametrize("bad", ["abc", 70000, -1, [8765]])
def test_a_port_that_cannot_be_listened_on_is_explained_not_traced(bad):
    from types import SimpleNamespace
    from loci import cli
    with pytest.raises(SystemExit, match="port"):
        cli.resolve_port(None, SimpleNamespace(http={"port": bad}))


def test_run_server_with_port_zero_reports_the_port_it_got(monkeypatch, capsys):
    class FakeServer:
        def __init__(self, bound):
            self.bound = bound

        def __call__(self, addr, handler):
            self.bound["asked"] = addr[1]
            self.server_address = (addr[0], 43111)
            return self

        def serve_forever(self):
            pass

    bound = _fake_brain(monkeypatch, FakeServer)
    http_api.run_server(_cfg(), "127.0.0.1", 0)
    out = capsys.readouterr().out
    assert bound["asked"] == 0                        # 0 reached the socket layer
    assert "127.0.0.1:43111" in out                   # and the real port was printed
    assert "was taken" not in out                     # 0 was not "taken"


def test_an_out_of_range_port_is_explained_not_traced(monkeypatch):
    monkeypatch.setattr(http_api, "Brain", lambda: type(
        "B", (), {"_ensure": lambda self: None})())
    monkeypatch.setattr(http_api, "Audit", lambda: None)
    monkeypatch.setattr(http_api, "_auth_table", lambda cfg: [
        {"token": "t", "role": "admin", "label": "t"}])
    monkeypatch.setattr(http_api, "_make_handler", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="port"):
        http_api.run_server(_cfg(), "127.0.0.1", 70000)   # OverflowError is not an OSError
