"""README's MCP tool table must not drift from the registry again.

The table still listed 10 tools after state/health shipped (15 total) — the
docs a 100k-follower share sends people to undercounted the product. Parses
the tool names out of mcp_server.py's TOOLS literal with `ast` instead of
importing the module, so this test needs no openai/chromadb and runs anywhere.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MCP = ROOT / "src" / "loci" / "mcp_server.py"


def registered_tools() -> set[str]:
    tree = ast.parse(MCP.read_text(encoding="utf-8"))
    for node in tree.body:
        if not (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "TOOLS" for t in node.targets)):
            continue
        names = set()
        for entry in node.value.elts:
            for key, value in zip(entry.keys, entry.values):
                if isinstance(key, ast.Constant) and key.value == "name" \
                        and isinstance(value, ast.Constant):
                    names.add(value.value)
        return names
    raise AssertionError("TOOLS not found in mcp_server.py")


def readme_table() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("| MCP tools | Purpose |")
    end = text.index("\n\n", start)
    return text[start:end]


def test_every_registered_tool_appears_in_the_readme_table():
    table = readme_table()
    for name in registered_tools():
        assert f"`{name}`" in table, f"{name} is registered but missing from README's tool table"


def test_readme_table_has_no_ghost_tools():
    names = set(re.findall(r"`(brain_[a-z_]+)`", readme_table()))
    assert names == registered_tools(), (
        f"ghosts={names - registered_tools()} missing={registered_tools() - names}")
