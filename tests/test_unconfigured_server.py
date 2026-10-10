"""Regression: an unconfigured environment must NEVER kill the server process.

Found via Glama's hosted inspection: the inspector handshakes fine, then calls
a tool; the old code raised SystemExit (from config.validate) on first tool
call, the process died, and the follow-up ping failed with 'Connection closed'."""
import contextlib
import io

import pytest

import loci.cli as cli_module
import loci.mcp_server as mcp_module
from conftest import patch_brain_config
from loci import config
from loci.mcp_server import Brain, handle_message


class UnconfiguredCfg:
    """Loads fine but fails validate() — like a container with no config.toml."""

    llm = {"api_key": ""}
    embed = {"api_key": ""}
    sources = []
    chunk = {"size": 800, "overlap": 100}
    top_k = {"search": 5}
    retrieval = {}
    watch = {}
    store = {"path": "unused"}

    def validate(self):
        raise SystemExit("Missing configuration: llm.api_key is not set ...")


def unconfigured_brain(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_module.config, "load", lambda path="config.toml": UnconfiguredCfg())
    b = Brain()
    return b


def test_all_tools_survive_unconfigured(monkeypatch, tmp_path):
    b = unconfigured_brain(monkeypatch, tmp_path)
    assert "not configured" in b.search("anything").lower()
    assert "not configured" in b.ask("anything").lower()
    assert "not configured" in b.links("anything").lower()
    assert "not configured" in b.stats().lower()
    assert "not configured" in b.ingest().lower()
    b.search("again")  # second call: still alive, no state corruption


def test_unconfigured_resources_list_only_stats(monkeypatch, tmp_path):
    b = unconfigured_brain(monkeypatch, tmp_path)
    resp = handle(msg := {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, b) \
        if False else None
    from loci.mcp_server import handle_message
    r = handle_message({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, b)
    uris = [x["uri"] for x in r["result"]["resources"]]
    assert uris == ["brain://stats"]


def test_unconfigured_note_resource_is_not_found(monkeypatch, tmp_path):
    from loci.mcp_server import handle_message
    b = unconfigured_brain(monkeypatch, tmp_path)
    r = handle_message({"jsonrpc": "2.0", "id": 2, "method": "resources/read",
                        "params": {"uri": "brain://note/%2Fa.md"}}, b)
    assert r["error"]["code"] == -32002


def test_brain_still_works_when_configured(monkeypatch, tmp_path):
    """Guard must not fire for a healthy config."""
    class FakeRetriever:
        top_k = 5

        def search(self, query, tag=None, path_contains=None, k=None):
            return [{"id": "1", "text": "hit", "source": "a.md", "chunk": 0,
                     "section": "S", "tags": "", "links": "", "mtime": 0.0,
                     "distance": 0.1}]

    patch_brain_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module, "build", lambda cfg: (None, None))
    monkeypatch.setattr(cli_module, "make_retriever",
                        lambda cfg, e, s: FakeRetriever())
    b = Brain()
    out = b.search("x")
    assert "not configured" not in out and "a.md" in out


def test_config_warnings_go_to_stderr(tmp_path, capsys):
    """stdio hosts: protocol stream must stay free of warning text."""
    import sys
    p = tmp_path / "missing.toml"
    config.load(str(p))
    captured = capsys.readouterr()
    assert captured.out == ""          # stdout stays clean
    assert "warn" in captured.err
