import loci.cli as cli_module
from conftest import patch_brain_config
from loci.mcp_server import Brain, handle_message
from loci.store import Store


class FakeStore:
    """Minimal store double for MCP resource tests."""

    def __init__(self):
        self._texts = {"/n/alpha.md": ["alpha part one", "alpha part two"]}

    def per_source(self):
        return {p: len(v) for p, v in self._texts.items()}

    def texts_of(self, path):
        return self._texts.get(path, [])

    def count(self):
        return sum(len(v) for v in self._texts.values())


def wired_brain(monkeypatch, tmp_path):
    patch_brain_config(monkeypatch, tmp_path)
    store = FakeStore()
    monkeypatch.setattr(cli_module, "build", lambda cfg: (None, store))
    b = Brain()
    b._ensure()
    return b


def msg(id, method, params=None):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def test_initialize_advertises_resources_and_prompts():
    resp = handle_message(msg(1, "initialize",
                              {"protocolVersion": "2024-11-05"}), Brain())
    caps = resp["result"]["capabilities"]
    assert "tools" in caps and "resources" in caps and "prompts" in caps


def test_resources_lists_stats_and_notes(monkeypatch, tmp_path):
    b = wired_brain(monkeypatch, tmp_path)
    resp = handle_message(msg(2, "resources/list"), b)
    uris = [r["uri"] for r in resp["result"]["resources"]]
    assert uris[0] == "brain://stats"
    assert any(r["name"] == "alpha.md" and r["uri"].startswith("brain://note/")
               and r["description"] == "2 chunks" for r in resp["result"]["resources"])


def test_resource_read_returns_joined_note(monkeypatch, tmp_path):
    import urllib.parse
    b = wired_brain(monkeypatch, tmp_path)
    uri = "brain://note/" + urllib.parse.quote("/n/alpha.md", safe="")
    resp = handle_message(msg(3, "resources/read", {"uri": uri}), b)
    content = resp["result"]["contents"][0]
    assert content["mimeType"] == "text/markdown"
    assert "alpha part one" in content["text"] and "alpha part two" in content["text"]


def test_resource_read_stats(monkeypatch, tmp_path):
    b = wired_brain(monkeypatch, tmp_path)
    resp = handle_message(msg(4, "resources/read", {"uri": "brain://stats"}), b)
    assert resp["result"]["contents"][0]["mimeType"] == "text/plain"


def test_resource_read_unknown_uri_is_minus_32002(monkeypatch, tmp_path):
    b = wired_brain(monkeypatch, tmp_path)
    resp = handle_message(msg(5, "resources/read",
                              {"uri": "brain://note/%2Fmissing.md"}), b)
    assert resp["error"]["code"] == -32002
    resp = handle_message(msg(6, "resources/read", {"uri": "brain://nope"}), b)
    assert resp["error"]["code"] == -32002


def test_prompts_list_exposes_three_templates():
    resp = handle_message(msg(7, "prompts/list"), Brain())
    names = [p["name"] for p in resp["result"]["prompts"]]
    assert names == ["brain-briefing", "study-plan", "contradiction-check"]
    for p in resp["result"]["prompts"]:
        assert p["arguments"] and p["arguments"][0]["required"] is True


def test_prompts_get_substitutes_topic():
    resp = handle_message(msg(8, "prompts/get",
                              {"name": "brain-briefing",
                               "arguments": {"topic": "vector dbs"}}), Brain())
    prompt_msg = resp["result"]["messages"][0]
    assert prompt_msg["role"] == "user"
    assert "vector dbs" in prompt_msg["content"]["text"]
    assert "{topic}" not in prompt_msg["content"]["text"]


def test_prompts_get_unknown_or_missing_args():
    resp = handle_message(msg(9, "prompts/get", {"name": "nope"}), Brain())
    assert resp["error"]["code"] == -32602
    resp = handle_message(msg(10, "prompts/get",
                              {"name": "brain-briefing", "arguments": {}}), Brain())
    assert "missing required argument" in resp["error"]["message"]


def test_store_texts_of_orders_chunks(tmp_path):
    store = Store(str(tmp_path / "db"))
    store.upsert_chunks([{"text": "second part", "section": ""},
                         {"text": "first part", "section": ""}],
                        [[0.0] * 4, [0.0] * 4], "/n/x.md", "h")
    texts = store.texts_of("/n/x.md")
    assert texts == ["second part", "first part"]  # stored order by chunk index
    assert store.texts_of("/n/missing.md") == []
