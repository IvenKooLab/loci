"""MCP server: expose the second brain as tools and resources over stdio —
zero dependencies.

Implements the Model Context Protocol (newline-delimited JSON-RPC 2.0):
initialize / ping / tools/list / tools/call / resources/list / resources/read /
prompts/list / prompts/get. Any MCP host (Claude Desktop, Cursor, Cline, ...)
can mount it:

    {
      "mcpServers": {
        "second-brain": {
          "command": "python",
          "args": ["/path/to/second-brain-rag/mcp_server.py"]
        }
      }
    }
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from second_brain import __version__, config  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"

PROMPTS: dict[str, dict] = {
    "brain-briefing": {
        "description": "A structured briefing on a topic from your own notes.",
        "arguments": [{"name": "topic", "description": "what to brief on",
                       "required": True}],
        "template": ("Search my knowledge base thoroughly for everything about "
                     "{topic}. Then give me a structured briefing: (1) what I "
                     "already know, (2) key decisions and their rationale, "
                     "(3) open questions my notes don't answer. Cite sources "
                     "for every point."),
    },
    "study-plan": {
        "description": "Turn scattered notes on a topic into a learning plan.",
        "arguments": [{"name": "topic", "description": "the subject to learn",
                       "required": True}],
        "template": ("Based on my notes about {topic}, assess my current level, "
                     "identify what I haven't captured yet, and propose a "
                     "step-by-step study plan that fills the gaps. Reference "
                     "the notes I already have where relevant."),
    },
    "contradiction-check": {
        "description": "Find contradictions and stale claims across your notes.",
        "arguments": [{"name": "topic", "description": "topic to audit",
                       "required": True}],
        "template": ("Collect everything my knowledge base says about {topic} "
                     "and look for: direct contradictions between notes, "
                     "claims that look outdated, and important aspects with "
                     "no coverage at all. Report each finding with its sources."),
    },
}

TOOLS = [
    {
        "name": "brain_search",
        "description": "Search the personal knowledge base. Returns ranked excerpts "
                       "with file path and section breadcrumbs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what to look for"},
                "k": {"type": "integer", "description": "number of hits (default 5)"},
                "tag": {"type": "string", "description": "filter by frontmatter tag"},
                "in": {"type": "string",
                       "description": "only hits whose source path contains this substring"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "brain_ask",
        "description": "Ask the knowledge base a question. Returns an LLM answer "
                       "grounded in retrieved excerpts, with [source: path > section] citations. "
                       "Set verify=true to append a claim-by-claim faithfulness audit.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"},
                           "verify": {"type": "boolean",
                                      "description": "audit the answer against the sources"}},
            "required": ["question"],
        },
    },
    {
        "name": "brain_links",
        "description": "Show the [[wikilink]] graph around a note: which notes it "
                       "links to and which notes link back to it.",
        "inputSchema": {
            "type": "object",
            "properties": {"note": {"type": "string",
                                    "description": "note name (file stem) to look up"}},
            "required": ["note"],
        },
    },
    {
        "name": "brain_stats",
        "description": "Index overview: total chunks, chunks per source file.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "brain_ingest",
        "description": "Incrementally (re)index the configured source directories. "
                       "Safe to call repeatedly; only changed files are re-embedded.",
        "inputSchema": {
            "type": "object",
            "properties": {"force": {"type": "boolean",
                                     "description": "re-embed everything, ignoring hashes"}},
        },
    },
]


class Brain:
    """Lazily-built access to the pipeline; one instance per server process."""

    def __init__(self):
        self._cfg = None
        self._retriever = None
        self._store = None

    def _ensure(self):
        if self._retriever is None:
            from second_brain.cli import build, make_retriever
            cfg = config.load()
            cfg.validate()
            embedder, store = build(cfg)
            self._cfg = cfg
            self._store = store
            self._retriever = make_retriever(cfg, embedder, store)
        return self._cfg, self._retriever

    def search(self, query: str, k: int | None = None,
               tag: str | None = None, path_contains: str | None = None) -> str:
        cfg, retriever = self._ensure()
        if k:
            retriever.top_k = k
        hits = retriever.search(query, tag=tag, path_contains=path_contains)
        blocks = []
        for i, h in enumerate(hits, 1):
            where = h["source"] + (f" > {h['section']}" if h["section"] else "")
            blocks.append(f"[{i}] {where}\n{h['text'][:500]}")
        return "\n\n".join(blocks) or "(no results)"

    def ask(self, question: str, verify: bool = False) -> str:
        cfg, retriever = self._ensure()
        hits = retriever.search(question)
        if not hits:
            return "(nothing relevant in the knowledge base)"
        from second_brain.retriever import answer, verify_answer
        reply = answer(cfg.llm, question, hits)
        if verify:
            reply += "\n\n" + verify_answer(cfg.llm, question, reply, hits)
        return reply

    def ingest(self, force: bool = False) -> str:
        cfg, _ = self._ensure()
        from second_brain.cli import cmd_ingest
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):  # keep the protocol stream clean
            cmd_ingest(cfg, force=force)
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        return "\n".join(lines[-3:]) or "ingest finished"

    def links(self, note: str) -> str:
        self._ensure()
        from second_brain.cli import cmd_links
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_links(self._cfg, note)
        return buf.getvalue().strip() or f"(no note matching '{note}')"

    def stats(self) -> str:
        self._ensure()
        from second_brain.cli import cmd_stats
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_stats(self._cfg)
        return buf.getvalue().strip()

    # ---- MCP resources ----

    def resources_list(self) -> list[dict]:
        self._ensure()
        resources = [{
            "uri": "brain://stats",
            "name": "index-stats",
            "description": "What is in the index: chunks per source, models, settings.",
            "mimeType": "text/plain",
        }]
        for path, n in sorted(self._store.per_source().items()):
            resources.append({
                "uri": f"brain://note/{quote(path, safe='')}",
                "name": Path(path).name,
                "description": f"{n} chunks",
                "mimeType": "text/markdown",
            })
        return resources

    def resource_read(self, uri: str) -> list[dict]:
        self._ensure()
        if uri == "brain://stats":
            return [{"uri": uri, "mimeType": "text/plain", "text": self.stats()}]
        prefix = "brain://note/"
        if uri.startswith(prefix):
            path = unquote(uri[len(prefix):])
            texts = self._store.texts_of(path)
            if not texts:
                raise KeyError(path)
            return [{"uri": uri, "mimeType": "text/markdown",
                     "text": "\n\n".join(texts)}]
        raise KeyError(uri)


def _call_tool(brain: Brain, name: str, args: dict) -> str:
    if name == "brain_search":
        return brain.search(args["query"], k=args.get("k"),
                            tag=args.get("tag"), path_contains=args.get("in"))
    if name == "brain_ask":
        return brain.ask(args["question"], verify=bool(args.get("verify")))
    if name == "brain_links":
        return brain.links(args["note"])
    if name == "brain_stats":
        return brain.stats()
    if name == "brain_ingest":
        return brain.ingest(force=bool(args.get("force")))
    raise ValueError(f"unknown tool: {name}")


def _ok(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def handle_message(msg: dict, brain: Brain) -> dict | None:
    """Handle one JSON-RPC message. Returns None for notifications (no response)."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    if "id" not in msg:  # notification — never respond
        return None
    try:
        if method == "initialize":
            params = msg.get("params") or {}
            version = params.get("protocolVersion") or PROTOCOL_VERSION
            return _ok(req_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "second-brain-rag", "version": __version__},
            })
        if method == "ping":
            return _ok(req_id, {})
        if method == "tools/list":
            return _ok(req_id, {"tools": TOOLS})
        if method == "resources/list":
            try:
                return _ok(req_id, {"resources": brain.resources_list()})
            except Exception as e:
                return _err(req_id, -32603, f"{type(e).__name__}: {e}")
        if method == "resources/read":
            uri = (msg.get("params") or {}).get("uri", "")
            try:
                return _ok(req_id, {"contents": brain.resource_read(uri)})
            except KeyError:
                return _err(req_id, -32002, f"resource not found: {uri}")
            except Exception as e:
                return _err(req_id, -32603, f"{type(e).__name__}: {e}")
        if method == "prompts/list":
            return _ok(req_id, {"prompts": [
                {"name": name, "description": spec["description"],
                 "arguments": spec["arguments"]}
                for name, spec in PROMPTS.items()]})
        if method == "prompts/get":
            params = msg.get("params") or {}
            name, args = params.get("name", ""), params.get("arguments") or {}
            spec = PROMPTS.get(name)
            if not spec:
                return _err(req_id, -32602, f"unknown prompt: {name}")
            missing = [a["name"] for a in spec["arguments"]
                       if a.get("required") and not str(args.get(a["name"], "")).strip()]
            if missing:
                return _err(req_id, -32602,
                            f"missing required argument(s): {', '.join(missing)}")
            text = spec["template"].format(**{**args, "topic": args.get("topic", "")})
            return _ok(req_id, {"description": spec["description"],
                                "messages": [{"role": "user",
                                              "content": {"type": "text",
                                                          "text": text}}]})
        if method == "tools/call":
            params = msg.get("params") or {}
            try:
                text = _call_tool(brain, params.get("name", ""),
                                  params.get("arguments") or {})
                return _ok(req_id, {"content": [{"type": "text", "text": text}],
                                    "isError": False})
            except Exception as e:
                return _ok(req_id, {"content": [
                    {"type": "text", "text": f"{type(e).__name__}: {e}"}],
                    "isError": True})
        return _err(req_id, -32601, f"method not found: {method}")
    except Exception as e:
        return _err(req_id, -32603, f"{type(e).__name__}: {e}")


def serve() -> None:
    """stdio loop: one JSON-RPC message per line; only protocol JSON hits stdout."""
    brain = Brain()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps(_err(None, -32700, f"parse error: {e}")),
                  flush=True)
            continue
        resp = handle_message(msg, brain)
        if resp is not None:
            print(json.dumps(resp, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    serve()
