"""One version, read from one place, visible where people look for it.

`pyproject.toml` is the only place the number is *declared*; everything else
reads it at runtime (installed metadata first, pyproject second for a source
checkout). These tests pin that so a release bump cannot leave the console,
`loci doctor` or the MCP handshake reporting a stale version.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

import loci
from loci.http_api import Audit, _make_handler

ROOT = Path(loci.__file__).resolve().parents[2]   # repo root, wherever the tests run from


def declared_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("installed package: no pyproject next to it")
    text = pyproject.read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


def test_version_is_a_real_string():
    assert isinstance(loci.__version__, str)
    assert loci.__version__.strip()
    assert loci.__version__ != "0.0.0+source" or not (ROOT / "pyproject.toml").exists()


def test_source_checkout_reports_the_declared_version():
    # installed metadata wins when present; in a source tree the declaration is
    # the source of truth, and they must agree after a release bump
    from importlib.metadata import PackageNotFoundError, version
    try:
        installed = version("loci-rag")
    except PackageNotFoundError:
        installed = None
    if installed is None:
        assert loci.__version__ == declared_version()
    else:
        assert loci.__version__ == installed


def test_cli_reports_the_version(capsys):
    from loci import cli
    argv = sys.argv
    sys.argv = ["loci", "--version"]
    try:
        with pytest.raises(SystemExit) as exit_info:
            cli.main()
    finally:
        sys.argv = argv
    assert exit_info.value.code == 0
    assert loci.__version__ in capsys.readouterr().out


def test_doctor_ends_with_the_version(tmp_path, monkeypatch, capsys):
    from loci import cli
    monkeypatch.chdir(tmp_path)
    cfg = SimpleNamespace(
        llm={"api_key": "", "base_url": "", "model": "x"},
        embed={"api_key": "", "base_url": "", "model": "y"},
        sources=[], retrieval={}, store={"path": str(tmp_path / "db")})
    cli.cmd_doctor(cfg)
    out = capsys.readouterr().out
    assert out.rstrip().endswith(f"loci {loci.__version__} · python "
                                 f"{sys.version.split()[0]} · {__import__('platform').system().lower()}")


@pytest.fixture
def server():
    cfg = SimpleNamespace(memories={"path": "/tmp"},
                          http={"icons": "/tmp", "local_admin": False})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(
        SimpleNamespace(), cfg,
        [{"token": "t", "role": "admin", "label": "test"}], Audit()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def test_health_reports_version_for_the_console(server):
    import http.client
    conn = http.client.HTTPConnection(*server.server_address, timeout=4)
    conn.request("GET", "/health", headers={"Authorization": "Bearer t"})
    res = conn.getresponse()
    assert res.status == 200
    data = json.loads(res.read())
    assert data["version"] == loci.__version__
    assert data["me"]["role"] == "admin"       # existing field untouched


def test_console_markup_has_the_version_slot():
    html = (ROOT / "src/loci/web/index.html").read_text(encoding="utf-8")
    assert 'id="ver"' in html
    app = (ROOT / "src/loci/web/app.js").read_text(encoding="utf-8")
    assert '#ver' in app and "h.version" in app
