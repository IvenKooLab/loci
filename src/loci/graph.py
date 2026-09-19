"""Lightweight knowledge graph over memories and wiki pages.

Entities and relations are LLM-extracted into a single graph.json next to the
vector store — no graph database, human-readable, hand-editable. Edges cite
their source file, so graph facts stay as traceable as everything else in loci.

Incremental: each source file is processed once (content-hash tracked); edits
re-extract only that file's edges."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

EXTRACT_PROMPT = (
    "Extract factual relationships from the text as (subject, predicate, object) "
    "triples. Rules: keep entities short (1-3 words, consistent naming — prefer "
    "the exact term used in the text); predicates are lowercase verbs "
    "(uses, speeds_up, replaces, depends_on, part_of, contradicts, …); only "
    "state what the text supports; skip trivia and self-loops; max 6 triples. "
    'Reply with ONLY a JSON array like [["T8", "speeds_up", "drafts"], ...]. '
    "Return [] if nothing worth extracting."
)


def graph_path(cfg) -> Path:
    return Path(cfg.store["path"]) / "graph.json"


def load_graph(cfg) -> dict:
    p = graph_path(cfg)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "processed": {}, "entities": {}, "edges": []}


def save_graph(cfg, graph: dict) -> None:
    p = graph_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _extract_triples(llm_cfg: dict, text: str) -> list[list[str]]:
    from openai import OpenAI
    client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
    resp = client.chat.completions.create(
        model=llm_cfg["model"],
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": text[:3000]},
        ],
        temperature=0.0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    # LLMs sometimes wrap the array in ```json fences or prose — recover it
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        triples = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for t in triples if isinstance(triples, list) else []:
        if (isinstance(t, list) and len(t) == 3
                and all(isinstance(x, str) and x.strip() for x in t)):
            out.append([x.strip() for x in t])
    return out


def build_graph(cfg, dirs: list[str] | None = None, force: bool = False) -> dict:
    """Extract entity-relation triples from memories/wiki files into graph.json.
    Returns a summary {files, new, edges, entities}."""
    from loci import chunker

    graph = load_graph(cfg)
    if dirs is None:
        dirs = [cfg.memories.get("path", "./memories"),
                cfg.wiki.get("path", "./wiki")]
    files = []
    for d in dirs:
        root = Path(d).expanduser()
        if root.exists():
            files.extend(sorted(root.rglob("*.md")))
    changed_files, new_edge_count = [], 0
    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        h = hashlib.sha1(content.encode("utf-8")).hexdigest()
        rel = str(f)
        if not force and graph["processed"].get(rel) == h:
            continue
        # drop this file's previous edges, keep others
        graph["edges"] = [e for e in graph["edges"] if e.get("source") != rel]
        if content.strip() and cfg.llm.get("api_key"):
            # chunk lightly: first chunk of the body is usually enough for notes
            chunks = chunker.split_markdown(content, 2000, 0)
            for ch in chunks[:2]:
                for s, p, o in _extract_triples(cfg.llm, ch["text"]):
                    graph["edges"].append(
                        {"s": s, "p": p, "o": o, "source": rel,
                         "ts": int(time.time())})
                    new_edge_count += 1
        graph["processed"][rel] = h
        changed_files.append(rel)
    # rebuild entity index
    entities: dict[str, dict] = {}
    for e in graph["edges"]:
        for role in ("s", "o"):
            name = e[role]
            ent = entities.setdefault(name, {"degree": 0, "sources": set()})
            ent["degree"] += 1
            ent["sources"].add(e["source"])
    graph["entities"] = {k: {"degree": v["degree"],
                             "sources": sorted(v["sources"])[:5]}
                         for k, v in entities.items()}
    save_graph(cfg, graph)
    return {"files": len(changed_files), "new": new_edge_count,
            "edges": len(graph["edges"]), "entities": len(graph["entities"])}


def query_graph(cfg, entity: str) -> dict:
    """All edges touching `entity` (case-insensitive), split in/out."""
    graph = load_graph(cfg)
    q = entity.strip().lower()
    out_edges = [e for e in graph["edges"] if e["s"].lower() == q]
    in_edges = [e for e in graph["edges"] if e["o"].lower() == q]
    hubs = sorted(graph["entities"].items(),
                  key=lambda kv: -kv[1]["degree"])[:10] if not q else []
    return {"entity": entity, "out": out_edges, "in": in_edges,
            "hubs": [{"name": n, "degree": d["degree"]} for n, d in hubs]}
