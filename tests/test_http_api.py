"""Offline HTTP regressions for console path boundaries and failure responses."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from loci.http_api import Audit, _make_handler


@pytest.fixture
def api(tmp_path, monkeypatch):
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "note.md").write_text("allowed", encoding="utf-8")
    outside = tmp_path / "memories-private"
    outside.mkdir()
    (outside / "secret.md").write_text("private", encoding="utf-8")
    (memories / "escape.md").symlink_to(outside / "secret.md")
    cfg = SimpleNamespace(memories={"path": str(memories)},
                          http={"icons": str(memories), "local_admin": False})
    monkeypatch.setattr("loci.harness.load_harnesses", lambda _: [])

    def fail(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    brain = SimpleNamespace(remember=fail, ingest=fail, harness_summarize=fail)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(
        brain, cfg, [{"token": "test", "role": "admin", "label": "test"}], Audit()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*server.server_address, timeout=3)
        try:
            conn.request(method, path, body=body,
                         headers={"Authorization": "Bearer test", **(headers or {})})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    yield request, memories, outside
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("name", ["../memories-private/secret.md", "escape.md"])
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_memory_cannot_escape_root(api, name, method):
    request, _, outside = api
    route = "/memory?" + urlencode({"name": name})
    body = json.dumps({"name": name, "text": "overwrite"}) if method == "POST" else None
    status, _ = request(method, route, body)
    assert status == 404
    assert (outside / "secret.md").read_text() == "private"


def test_source_file_uses_directory_boundaries(api):
    request, memories, outside = api
    for path in (outside / "secret.md", memories / "escape.md"):
        assert request("GET", "/source-file?" + urlencode({"path": str(path)}))[0] == 404
    status, body = request("GET", "/source-file?" + urlencode({"path": str(memories / "note.md")}))
    assert status == 200 and body["text"] == "allowed"


def test_listing_omits_outside_symlinks(api):
    request, _, _ = api
    status, body = request("GET", "/memories")
    assert status == 200
    assert [row["name"] for row in body["memories"]] == ["note.md"]
    assert request("GET", "/icons/escape.md")[0] == 404


@pytest.mark.parametrize("route", ["/remember", "/ingest", "/harness"])
def test_backend_failure_returns_json_instead_of_dropped_connection(api, route):
    request, _, _ = api
    status, body = request("POST", route, "{}")
    assert status == 500 and "backend unavailable" in body["error"]


@pytest.mark.parametrize("body", ["[]", "null", "42", '"text"', "{", b"\xff"])
def test_invalid_json_body_returns_400(api, body):
    request, _, _ = api
    assert request("POST", "/memory", body)[0] == 400


@pytest.mark.parametrize("length,status", [("-1", 400), ("nope", 400), (str((1 << 20) + 1), 413)])
def test_invalid_content_length_is_rejected_before_read(api, length, status):
    request, _, _ = api
    assert request("POST", "/memory", headers={"Content-Length": length})[0] == status


def test_source_file_decodes_url_exactly_once(api):
    request, memories, _ = api
    note = memories / "literal%20name.md"
    note.write_text("literal percent", encoding="utf-8")
    status, body = request("GET", "/source-file?" + urlencode({"path": str(note)}))
    assert status == 200 and body["text"] == "literal percent"
