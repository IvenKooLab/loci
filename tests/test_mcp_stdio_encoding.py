"""The MCP stdio transport is UTF-8, whatever the host's locale says.

A piped stdin/stdout is decoded with the ANSI code page on Windows (cp936 on
a Chinese install) unless UTF-8 mode happens to be on. CJK tool arguments
then arrived as mojibake (`任务A` was read as `浠诲姟A`, so the key saved was
wrong) and the replies left the process in an encoding no host can parse.
The child here runs without PYTHONUTF8 / PYTHONIOENCODING, the way a default
install launches it from Claude Desktop, Cursor or Cline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def test_cjk_tool_arguments_round_trip_without_utf8_mode(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("PYTHON")}

    def rpc(i, method, params):
        return json.dumps({"id": i, "method": method, "params": params},
                          ensure_ascii=False).encode("utf-8") + b"\n"

    payload = b"".join([
        rpc(1, "tools/call", {"name": "brain_state_save", "arguments":
                              {"type": "task", "key": "任务A", "data": {"x": 1}}}),
        rpc(2, "tools/call", {"name": "brain_state_list", "arguments": {}}),
    ])
    proc = subprocess.run([sys.executable, "-m", "loci.mcp_server"],
                          input=payload, capture_output=True, env=env,
                          cwd=str(tmp_path), timeout=120)
    # strict decode: the protocol stream must be valid UTF-8
    text = proc.stdout.decode("utf-8")
    replies = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert len(replies) == 2, text
    assert "任务A" in replies[0]["result"]["content"][0]["text"]
    # the key survived into the store, not just into the echo (the listing
    # shows file names, and state keys fold to one case)
    listed = replies[1]["result"]["content"][0]["text"]
    assert "task/" in listed and "任务" in listed and "浠" not in text
