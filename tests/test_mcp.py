import second_brain.cli as cli_module
from second_brain.mcp_server import PROTOCOL_VERSION, Brain, TOOLS, handle_message


def brain():
    return Brain()


def msg(id, method, params=None):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def test_initialize_returns_server_info():
    resp = handle_message(msg(1, "initialize",
                              {"protocolVersion": "2024-11-05"}), brain())
    assert resp["result"]["serverInfo"]["name"] == "second-brain-rag"
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in resp["result"]["capabilities"]


def test_initialize_echoes_client_protocol_version():
    resp = handle_message(msg(1, "initialize",
                              {"protocolVersion": "2099-01-01"}), brain())
    assert resp["result"]["protocolVersion"] == "2099-01-01"


def test_notifications_get_no_response():
    assert handle_message({"jsonrpc": "2.0",
                           "method": "notifications/initialized"}, brain()) is None


def test_ping():
    assert handle_message(msg(2, "ping"), brain())["result"] == {}


def test_tools_list_has_three_tools():
    resp = handle_message(msg(3, "tools/list"), brain())
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["brain_search", "brain_ask", "brain_ingest"]
    for tool in TOOLS:
        assert tool["inputSchema"]["type"] == "object"


def test_unknown_method_is_method_not_found():
    resp = handle_message(msg(4, "resources/read", {"uri": "x"}), brain())
    assert resp["error"]["code"] == -32601


def test_unknown_tool_returns_is_error():
    resp = handle_message(msg(5, "tools/call",
                              {"name": "nope", "arguments": {}}), brain())
    assert resp["result"]["isError"] is True
    assert "unknown tool" in resp["result"]["content"][0]["text"]


def test_search_tool_with_fake_pipeline(monkeypatch, tmp_path):
    class FakeRetriever:
        top_k = 5

        def search(self, query, tag=None):
            return [{"id": "1", "text": "found it", "source": "a.md",
                     "chunk": 0, "section": "S", "tags": "", "distance": 0.1}]

    monkeypatch.setattr(cli_module, "build", lambda cfg: (None, None))
    monkeypatch.setattr(cli_module, "make_retriever", lambda cfg, e, s: FakeRetriever())
    resp = handle_message(msg(6, "tools/call",
                              {"name": "brain_search",
                               "arguments": {"query": "x"}}), brain())
    text = resp["result"]["content"][0]["text"]
    assert resp["result"]["isError"] is False
    assert "a.md > S" in text and "found it" in text


def test_ingest_tool_keeps_protocol_stream_clean(monkeypatch, tmp_path):
    def fake_cmd_ingest(cfg, force=False):
        print("  + progress")
        print("Done: 1 added / 0 updated / 0 unchanged — 9 chunks in store")

    monkeypatch.setattr(cli_module, "build", lambda cfg: (None, None))
    monkeypatch.setattr(cli_module, "cmd_ingest", fake_cmd_ingest)

    import contextlib, io
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        resp = handle_message(msg(7, "tools/call",
                                  {"name": "brain_ingest",
                                   "arguments": {}}), brain())
    text = resp["result"]["content"][0]["text"]
    assert "Done: 1 added" in text            # the summary reaches the host
    assert len(text.splitlines()) <= 3        # progress noise is truncated
    assert captured.getvalue() == ""          # nothing leaked into real stdout


def test_protocol_version_constant_is_valid():
    assert PROTOCOL_VERSION.count("-") == 2
