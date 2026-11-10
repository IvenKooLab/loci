"""Decision history: what superseded what, and when it took effect.

A Markdown decision note ages badly when it is edited in place — the team
loses the fact that a later note replaced it. The convention this module reads
is deliberately small and lives in frontmatter, so it survives any editor:

    ---
    supersedes: use-staging            # a note stem or a path
    effective: 2026-03-01              # when this note took effect
    ---

`superseded_by:` is accepted too, for people who prefer pointing forward from
the old note to the new one. Nothing is derived from an LLM and nothing is
written back: the files stay the source of truth.
"""
from __future__ import annotations

import re
from pathlib import Path

from loci.loaders import parse_frontmatter

_FENCES = re.compile(r"^---\n(.*?)\n---\n", re.S)

# frontmatter keys, and the wording each one points
_FORWARD = ("supersedes", "superseded", "replaces")
_BACKWARD = ("superseded_by", "superseded-by", "replaced_by")


def _norm(value) -> str:
    """Frontmatter value → bare note stem, tolerant of [[links]] and paths."""
    text = str(value or "").strip().strip("\"'")
    text = text.strip("[]")
    text = text.split("|")[0]                      # [[target|alias]]
    text = text.split("#")[0]                      # [[target#heading]]
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    return text[:-3] if text.lower().endswith(".md") else text


def _meta_of(path: Path) -> dict:
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    if not head.startswith("---"):
        return {}
    meta, _ = parse_frontmatter(head)
    return meta


def collect(paths: list[Path]) -> dict[str, dict]:
    """{stem: {path, supersedes, superseded_by, effective}} over the given notes.

    Later files win on a stem collision, which matters because two directories
    can hold same-named notes — `history` says so rather than guessing.
    """
    out: dict[str, dict] = {}
    for path in paths:
        meta = _meta_of(path)
        if not meta:
            continue
        forward = next((_norm(meta[k]) for k in _FORWARD if meta.get(k)), "")
        backward = next((_norm(meta[k]) for k in _BACKWARD if meta.get(k)), "")
        effective = str(meta.get("effective", "")).strip()
        # a note that only carries `effective` is still a decision worth
        # tracking — it is usually the *original* the chain starts from, and
        # dropping it would leave every chain headless
        if not (forward or backward or effective):
            continue
        stem = path.stem
        entry = out.setdefault(stem, {"stem": stem, "path": str(path),
                                      "supersedes": "", "superseded_by": "",
                                      "effective": str(meta.get("effective", "")).strip()})
        entry["supersedes"] = forward or entry["supersedes"]
        entry["superseded_by"] = backward or entry["superseded_by"]
        entry["path"] = str(path)
        if entry["effective"] == "":
            entry["effective"] = str(meta.get("effective", "")).strip()
    # a forward pointer implies the reverse one, so a chain can be walked from
    # either end without requiring both files to be annotated. A target that
    # was not itself annotated still needs an entry, or the walk stops at it.
    for stem, entry in list(out.items()):
        target = entry["supersedes"]
        if not target:
            continue
        if target not in out:
            out[target] = {"stem": target, "path": "", "supersedes": "",
                           "superseded_by": "", "effective": ""}
        if not out[target]["superseded_by"]:
            out[target]["superseded_by"] = stem
    return out


def chain(table: dict, start: str) -> list[dict]:
    """The whole line containing `start`, oldest first.

    Walks back through `supersedes` to the original decision, then forward
    through `superseded_by` to whatever is current. Cycles stop at the repeat.
    """
    if start not in table:
        return []
    seen: set[str] = set()
    key = start
    while table.get(key, {}).get("supersedes") and table[key]["supersedes"] in table:
        nxt = table[key]["supersedes"]
        if nxt in seen or nxt == start:
            break
        seen.add(nxt)
        key = nxt
    order: list[dict] = []
    seen.clear()
    while key and key in table and key not in seen:
        seen.add(key)
        order.append(table[key])
        key = table[key].get("superseded_by", "")
    return order


def current_of(table: dict, start: str) -> dict | None:
    """The newest entry in `start`'s chain — the one that applies today."""
    line = chain(table, start)
    return line[-1] if line else None


def describe(line: list[dict]) -> str:
    """Human-readable chain: oldest first, `→` between supersessions."""
    if not line:
        return "(no supersession history recorded for this note)"
    parts = []
    for i, entry in enumerate(line):
        when = f" (effective {entry['effective']})" if entry["effective"] else ""
        tail = "" if i == len(line) - 1 else "  → superseded by"
        parts.append(f"  {i + 1}. {entry['stem']}{when}{tail}")
    return "decision history, oldest first:\n" + "\n".join(parts)


_CACHE: dict[tuple, dict] = {}


def table_for(sources: list[dict], memories: str = "") -> dict[str, dict]:
    """Supersession table over the configured sources, cached until they change.

    Cheap enough to call per answer: the cache key is the source paths plus the
    newest mtime under them, so an edited note re-scans and an idle instance
    pays only one stat walk.
    """
    roots = [Path(s["path"]).expanduser() for s in sources if s.get("path")]
    if memories:
        roots.append(Path(memories).expanduser())
    newest = 0.0
    files: list[Path] = []
    for root in roots:
        try:
            if root.is_file():
                files.append(root)
                newest = max(newest, root.stat().st_mtime)
                continue
            for path in root.rglob("*.md"):
                files.append(path)
                try:
                    newest = max(newest, path.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            continue
    key = (tuple(str(r) for r in roots), round(newest, 3))
    if key not in _CACHE:
        _CACHE.clear()                       # one instance's table at a time
        _CACHE[key] = collect(files)
    return _CACHE[key]


def annotate(hits: list[dict], table: dict[str, dict]) -> list[dict]:
    """Tag hits whose note has been superseded, so an answer can say so.

    Additive: hits gain `superseded_by` / `effective` keys, nothing is removed.
    """
    for hit in hits:
        stem = Path(str(hit.get("source", ""))).stem
        entry = table.get(stem)
        if entry and entry.get("superseded_by"):
            hit["superseded_by"] = entry["superseded_by"]
            if entry.get("effective"):
                hit["effective"] = entry["effective"]
    return hits
