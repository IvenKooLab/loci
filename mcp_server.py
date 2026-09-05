"""MCP entry point for hosts: `python mcp_server.py` (see README for host config)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from loci.mcp_server import serve  # noqa: E402

if __name__ == "__main__":
    serve()
