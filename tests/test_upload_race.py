"""Two concurrent uploads of the same name used to both pass the exists()
check and the second tmp.replace() silently overwrote the first — violating
the endpoint's own "never clobber silently" contract, and the index kept a
chunk whose source file no longer matched the first user's content."""
from __future__ import annotations

import base64
import json
import threading
import urllib.request

import pytest

from pathlib import Path

from loci.http_api import _make_handler, _auth_table, Audit
import loci.config as config


def _live_server(tmp_path, monkeypatch):
    """Real serve-http on an ephemeral port, offline embedder."""
    from loci.http_api import Server, QueryLog
    from loci.mcp_server import Brain
    from conftest import FakeEmbedder
    from loci.store import Store

    cfg = config.Config()
    for section, values in config.DEFAULTS.items():
        getattr(cfg, section).update(values)
    cfg.memories["path"] = str(tmp_path / "memories")
    cfg.store["path"] = str(tmp_path / "chroma")
    cfg.http["icons"] = str(tmp_path / "icons")
    cfg.embed["api_key"] = "offline"
    Path(cfg.memories["path"]).mkdir(parents=True)

    b = Brain.__new__(Brain)
    b._cfg = None
    b._retriever = None
    b._store = None
    b._config_error = None
    b._cfg = cfg
    monkeypatch.setattr("loci.cli.build", lambda c: (FakeEmbedder(), Store(cfg.store["path"])))
    b._ensure()

    entries = _auth_table(cfg)
    token = entries[0]["token"]
    handler = _make_handler(b, cfg, entries, Audit(), QueryLog())
    srv = Server(("127.0.0.1", 0), handler)
    import threading
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, token, cfg


def test_concurrent_same_name_uploads_neither_loses(tmp_path, monkeypatch):
    srv, token, cfg = _live_server(tmp_path, monkeypatch)
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    results: dict[str, dict] = {}

    def upload(tag):
        body = json.dumps({"name": "race.md",
                           "data": base64.b64encode(
                               f"content from {tag}".encode()).decode()}).encode()
        req = urllib.request.Request(
            base + "/upload", data=body, method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            results[tag] = json.loads(r.read())

    threads = [threading.Thread(target=upload, args=(t,)) for t in ("A", "B")]
    [t.start() for t in threads]
    [t.join() for t in threads]

    # both uploads succeeded, at DIFFERENT paths (no silent overwrite)
    assert results["A"]["path"] != results["B"]["path"]
    uploads = list((tmp_path / "memories" / "uploads").glob("race*.md"))
    contents = {p.read_text(encoding="utf-8") for p in uploads}
    assert contents == {"content from A", "content from B"}

    srv.shutdown()
