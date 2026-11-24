"""The stdio loop must survive anything a host writes that is valid JSON.

handle_message called msg.get(...) before checking what `msg` was. A JSON
array, a bare number, a string or null is all "valid JSON" — and each one
raised AttributeError out of the loop in serve(), killing the MCP server
process for the whole session. JSON-RPC answers those with Invalid Request.
"""
from __future__ import annotations

import json

import pytest

from loci.mcp_server import Brain, handle_message


@pytest.mark.parametrize("line", ["[1,2]", "null", "123", '"x"', "true", "[]"])
def test_non_object_messages_get_invalid_request_instead_of_raising(line):
    reply = handle_message(json.loads(line), Brain())
    assert isinstance(reply, dict)
    assert reply["error"]["code"] == -32600
    assert reply["id"] is None


def test_a_batch_of_requests_is_answered_with_invalid_request_not_a_crash():
    batch = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
    reply = handle_message(batch, Brain())
    assert reply["error"]["code"] == -32600


def test_a_real_request_still_works_after_the_bad_ones():
    brain = Brain()
    handle_message(None, brain)
    reply = handle_message({"jsonrpc": "2.0", "id": 7, "method": "ping"}, brain)
    assert reply == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_a_request_whose_id_is_present_still_gets_its_own_id_back():
    reply = handle_message({"jsonrpc": "2.0", "id": 3, "method": "no/such"}, Brain())
    assert reply["id"] == 3 and reply["error"]["code"] == -32601
