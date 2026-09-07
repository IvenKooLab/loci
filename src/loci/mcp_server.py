"""MCP server: expose the second brain as tools and resources over stdio —
zero dependencies.

Implements the Model Context Protocol (newline-delimited JSON-RPC 2.0):
initialize / ping / tools/list / tools/call / resources/list / resources/read /
prompts/list / prompts/get. Any MCP host (Claude Desktop, Cursor, Cline, ...)
can mount it:

    {
      "mcpServers": {
        "loci": {
          "command": "python",
          "args": ["/path/to/loci/mcp_server.py"]
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

from loci import __version__, config  # noqa: E402

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
        "description": "Search the personal knowledge base with hybrid retrieval "
                       "(vector similarity fused with BM25 keyword matching). Behavior: "
                       "returns up to k ranked excerpts, each with file path, heading "
                       "breadcrumb and similarity score; no LLM call is made. Usage: reach "
                       "for this when you need source material to quote, verify a claim, "
                       "or see what exists on a topic; use brain_ask when you want a "
                       "synthesized answer instead. Results are limited to the indexed "
                       "sources — run brain_ingest first if recent files are missing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what to look for, in any language"},
                "k": {"type": "integer", "description": "number of hits to return, 1-20 (default 5)"},
                "tag": {"type": "string", "description": "only results whose frontmatter tags contain this, e.g. 'rag' or 'memory'"},
                "in": {"type": "string", "description": "only results whose source path contains this substring, e.g. 'docs/en' or 'projects'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "brain_ask",
        "description": "Ask the knowledge base a question. Behavior: retrieves the most "
                       "relevant excerpts, then an LLM synthesizes an answer grounded ONLY in "
                       "them, ending with [source: path > section] citations. Usage: prefer "
                       "this over brain_search whenever a question needs synthesis or an "
                       "explanation; set verify=true to get a claim-by-claim audit "
                       "(supported / partial / unsupported) when accuracy matters more than speed.",
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
        "description": "Show the Obsidian-style [[wikilink]] graph around a note. Behavior: "
                       "lists every note the given note links to (outbound) and every note "
                       "that links back to it (inbound), based on the current index. Usage: "
                       "use to explore how a topic connects to others before asking questions, "
                       "or to find related notes when search keywords fail.",
        "inputSchema": {
            "type": "object",
            "properties": {"note": {"type": "string",
                                    "description": "note name (file stem) to look up"}},
            "required": ["note"],
        },
    },
    {
        "name": "brain_stats",
        "description": "Report what the index currently contains. Behavior: returns the "
                       "store path, total chunk count, chunk count per source file, the "
                       "embedding and chat models in use, and retrieval settings (hybrid, "
                       "rrf_k, top_k). Reads local metadata only — no LLM or embedding calls. "
                       "Usage: call before searching to see what is indexed, after "
                       "brain_ingest to confirm what changed, or whenever answers seem to be "
                       "missing a file you expected to be there. Takes no parameters.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "brain_remember",
        "description": "Store a durable memory (decision, fact, preference, lesson learned) "
                       "into the shared knowledge base. Behavior: writes a markdown note with "
                       "frontmatter tags into the memories directory and indexes it immediately, "
                       "so it is searchable within the same call. Memories persist across "
                       "sessions and are shared by every MCP host that mounts loci — write "
                       "from one IDE, recall from any other with brain_search or brain_ask. "
                       "Usage: use for decisions, facts, preferences and lessons worth "
                       "recording; do not use for ephemeral chit-chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "what to remember (plain text)"},
                "title": {"type": "string", "description": "short title; defaults to first line"},
                "tags": {"type": "array", "items": {"type": "string"},
                         "description": "optional extra tags (a 'memory' tag is always added)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "brain_forget",
        "description": "Retract memories that are wrong or outdated. Behavior: memory notes "
                       "matching the query move to a .trash folder (recoverable by hand) and "
                       "their chunks leave the index immediately; nothing is permanently "
                       "destroyed. Usage: use when a remembered fact was superseded or was a "
                       "mistake; check with brain_search first if you are unsure what matches.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string",
                                     "description": "matches memory filenames or content"}},
            "required": ["query"],
        },
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

    NOT_CONFIGURED = (
        "loci is running but not configured yet, so index-backed tools are "
        "unavailable in this environment. Setup (locally, where the index "
        "lives): copy config.example.toml to config.toml, fill in llm/embed "
        "API keys and at least one [[sources]] directory, then run "
        "`loci ingest`. After that all tools work."
    )

    def __init__(self):
        self._cfg = None
        self._retriever = None
        self._store = None
        self._config_error: str | None = None

    def _ensure(self):
        # never raises: an unconfigured environment leaves the server alive,
        # answering tool calls with guidance instead of killing the process
        if self._retriever is None and self._config_error is None:
            try:
                from loci.cli import build, make_retriever
                cfg = config.load()
                self._cfg = cfg          # keep even when invalid: brain_remember
                cfg.validate()           # still needs the memories path
                embedder, store = build(cfg)
            except SystemExit as e:
                self._config_error = str(e)
                return self._cfg, None
            except Exception as e:
                self._config_error = f"{type(e).__name__}: {e}"
                return self._cfg, None
            self._cfg = cfg
            self._store = store
            self._retriever = make_retriever(cfg, embedder, store)
        return self._cfg, self._retriever

    def _guard(self) -> str | None:
        """Guidance text when the pipeline is unavailable; None when ready."""
        self._ensure()
        return self.NOT_CONFIGURED if self._config_error else None

    def search(self, query: str, k: int | None = None,
               tag: str | None = None, path_contains: str | None = None) -> str:
        if err := self._guard():
            return err
        cfg, retriever = self._cfg, self._retriever
        try:
            k = int(k) if k is not None else None
        except (TypeError, ValueError):
            k = None
        # k rides as a per-call override — never mutates retriever state
        hits = retriever.search(query, tag=tag, path_contains=path_contains, k=k)
        blocks = []
        for i, h in enumerate(hits, 1):
            where = h["source"] + (f" > {h['section']}" if h["section"] else "")
            blocks.append(f"[{i}] {where}\n{h['text'][:500]}")
        return "\n\n".join(blocks) or "(no results)"

    def ask(self, question: str, verify: bool = False) -> str:
        if err := self._guard():
            return err
        cfg, retriever = self._cfg, self._retriever
        hits = retriever.search(question)
        if not hits:
            return "(nothing relevant in the knowledge base)"
        from loci.retriever import answer, verify_answer
        reply = answer(cfg.llm, question, hits)
        if verify:
            reply += "\n\n" + verify_answer(cfg.llm, question, reply, hits)
        return reply

    def ingest(self, force: bool = False) -> str:
        if err := self._guard():
            return err
        cfg = self._cfg
        from loci.cli import cmd_ingest
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):  # keep the protocol stream clean
            cmd_ingest(cfg, force=force)
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        return "\n".join(lines[-3:]) or "ingest finished"

    def links(self, note: str) -> str:
        if err := self._guard():
            return err
        from loci.cli import cmd_links
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_links(self._cfg, note)
        return buf.getvalue().strip() or f"(no note matching '{note}')"

    def stats(self) -> str:
        if err := self._guard():
            return err
        from loci.cli import cmd_stats
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_stats(self._cfg)
        return buf.getvalue().strip()

    # ---- cross-session memory (write + forget; recall = search/ask) ----

    def remember(self, text: str, title: str | None = None,
                 tags: list[str] | None = None) -> str:
        from loci.memories import index_memory_file, write_memory
        self._ensure()
        mem_dir = (self._cfg.memories or {}).get("path", "./memories") \
            if self._cfg else "./memories"
        path = write_memory(mem_dir, text, title=title, tags=tags)
        if self._config_error or self._retriever is None:
            return (f"stored: {path}\n"
                    "not indexed yet (no working embedder in this environment) — "
                    "run brain_ingest or `loci ingest` where loci is configured")
        n = index_memory_file(self._cfg, path)
        return f"remembered: {path} ({n} chunks, searchable now)"

    def forget(self, query: str) -> str:
        if err := self._guard():
            return err
        from loci.memories import forget_memory
        mem_dir = self._cfg.memories.get("path", "./memories")
        moved = forget_memory(mem_dir, query)
        for p in moved:
            self._store.delete_file(str(Path(p).resolve()))
        if not moved:
            return f"(no memory matching '{query}')"
        return "forgot:\n" + "\n".join(f"  - {m}" for m in moved)

    # ---- MCP resources ----

    def resources_list(self) -> list[dict]:
        self._ensure()
        resources = [{
            "uri": "brain://stats",
            "name": "index-stats",
            "description": "What is in the index: chunks per source, models, settings.",
            "mimeType": "text/plain",
        }]
        if self._config_error:   # unconfigured: only the stats resource exists
            return resources
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
        if self._config_error and uri != "brain://stats":
            raise KeyError(uri)   # per-note resources don't exist when unconfigured
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
    if name == "brain_remember":
        return brain.remember(args["text"], title=args.get("title"),
                              tags=args.get("tags"))
    if name == "brain_forget":
        return brain.forget(args["query"])
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
                "serverInfo": {"name": "loci", "version": __version__},
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
