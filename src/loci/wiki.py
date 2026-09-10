"""Wiki generation: distill everything the index knows about a topic into one
curated wiki page. This is loci's memory-consolidation layer — raw notes and
memories get distilled into stable, cross-linked pages that are indexed like
any other source.

Page lifecycle: retrieve material -> LLM synthesis -> atomic write into the
wiki directory -> immediate indexing. Regenerating a topic overwrites its page
(wikis are curated, one page per slug)."""
from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from loci.memories import slugify

WIKI_PROMPT = (
    "You are the editor of a personal knowledge wiki. Distill the provided "
    "source excerpts into ONE well-structured wiki page about the given topic. "
    "Rules: 1) short sections — a one-paragraph overview first, then key "
    "facts and details; 2) link related concepts inline using [[wikilinks]] "
    "(double square brackets); 3) state only what the excerpts support, and "
    "mark anything uncertain with (?); 4) write in the dominant language of "
    "the excerpts; 5) return ONLY the markdown page body, no code fences."
)


def generate_wiki_page(cfg, topic: str, k: int = 12) -> dict:
    """Retrieve up to k excerpts about `topic`, synthesize a wiki page, write
    and index it. Raises LookupError when the index has nothing on the topic;
    other errors propagate (LLM down, etc.). Returns a summary dict."""
    from loci.cli import build, make_retriever

    embedder, store = build(cfg)
    retriever = make_retriever(cfg, embedder, store)
    hits = retriever.search(topic, k=k)
    # self-reference guard: never cite the wiki's own pages as material,
    # or regeneration would grow the page without bound
    wiki_root = str(Path(str(cfg.wiki["path"])).expanduser().resolve())
    wiki_root = wiki_root.replace("\\", "/").lower().rstrip("/")
    hits = [h for h in hits
            if not (lambda src: src == wiki_root or src.startswith(wiki_root + "/"))(
                h["source"].replace("\\", "/").lower())]
    if not hits:
        raise LookupError(f"nothing in the index about '{topic}' — run brain_ingest first")

    client = OpenAI(base_url=cfg.llm["base_url"], api_key=cfg.llm["api_key"])
    context = "\n\n---\n\n".join(
        f"[excerpt {i + 1} | {h['source']}"
        + (f" > {h['section']}" if h.get("section") else "")
        + f"]\n{h['text']}" for i, h in enumerate(hits))
    resp = client.chat.completions.create(
        model=cfg.llm["model"],
        messages=[
            {"role": "system", "content": WIKI_PROMPT},
            {"role": "user", "content": f"Topic: {topic}\n\nSource excerpts:\n\n{context}"},
        ],
        temperature=0.2,
    )
    body = (resp.choices[0].message.content or "").strip()
    if not body:
        raise ValueError("the LLM returned an empty page")

    page_path = write_wiki_page(cfg, topic, body, hits)
    from loci.memories import index_memory_file
    n = index_memory_file(cfg, str(page_path))
    return {"path": str(page_path), "chunks": n, "sources": len(hits), "topic": topic}


def write_wiki_page(cfg, topic: str, body: str, hits: list[dict]) -> Path:
    """Compose frontmatter + LLM body + source list; atomic write."""
    slug = slugify(topic)
    wiki_dir = Path(cfg.wiki["path"]).expanduser()
    wiki_dir.mkdir(parents=True, exist_ok=True)
    page = wiki_dir / f"{slug}.md"

    sources = "\n".join(
        f"- {h['source']}" + (f" > {h['section']}" if h.get("section") else "")
        for h in hits)
    from datetime import datetime
    front = ("---\n"
             f"tags: [wiki, {slug}]\n"
             f"topic: {topic}\n"
             f"generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
             f"sources: {len(hits)}\n"
             "---\n")
    tmp = page.with_suffix(".md.tmp")
    tmp.write_text(f"{front}{body}\n\n## Sources\n\n{sources}\n", encoding="utf-8")
    tmp.replace(page)                    # atomic + overwrites on regeneration
    return page
