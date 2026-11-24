"""Knowledge-base governance: find what can no longer be trusted.

An index does not decay because retrieval got worse. It decays because the
world moved and the corpus did not: last quarter's policy is still there, still
plausible, still confidently cited. Adding documents does not fix that — it
adds more plausible candidates to a similarity score that has no notion of
"still in force".

This module is the read-only half of the answer. It never edits, moves or
deletes a file; it reports, in four categories, with evidence:

    superseded_live  frontmatter says it was replaced, but it is still indexed
    duplicate_truth  two active notes with the same title and different bodies
    dangling         `supersedes:` points at a note that does not exist
    stale            old, never cited, and nobody has confirmed it lately

`loci governance` prints it; `brain_governance` exposes the same over MCP.
Retiring is a separate, explicit action (`loci forget` / `brain_forget`),
because auto-deleting on a heuristic is how a governance tool loses work.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

# Frontmatter keys that mark a note as replaced. `supersede` (lowercase) is the
# canonical one; the aliases are what people actually type.
_SUPERSEDED = ("superseded_by", "superseded-by", "replaced_by")


def _paths(cfg) -> list[Path]:
    """Same discovery rules as scan_sources: folded .md/.markdown suffixes,
    no AppleDouble sidecars, nothing inside hidden directories — a `.trash`
    note must not show up in a governance report as if it were still live."""
    out: list[Path] = []
    for src in cfg.sources:
        p = Path(str(src.get("path", ""))).expanduser()
        if p.is_file():
            if p.suffix.lower() in (".md", ".markdown"):
                out.append(p)
            continue
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (".md", ".markdown"):
                continue
            if f.name.startswith("._") or f.name.startswith("~$"):
                continue
            try:
                rel = f.relative_to(p)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts[:-1]):
                continue
            out.append(f)
    return out


def _frontmatter(path: Path, limit: int = 4000) -> dict:
    """Parse the YAML subset loci already uses; cheap and tolerant."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")[:limit]
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta


def _threshold(value) -> int | None:
    """int(value), or None when it is not a whole number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stem(value: str) -> str:
    text = str(value or "").strip().strip("[]").split("|")[0].split("#")[0]
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(md|markdown)$", "", text, flags=re.I)


def _title(path: Path) -> str:
    meta = _frontmatter(path)
    if meta.get("title"):
        return meta["title"].strip().lower()
    try:
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip().lower()
            if line.strip():
                break
    except OSError:
        pass
    return _stem(path.name).lower()


def _hash(path: Path) -> str:
    import hashlib
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def scan(cfg, *, stale_days: int | None = None, cited: dict | None = None) -> dict:
    """One pass over the configured sources; returns findings, not actions."""
    files = _paths(cfg)
    by_stem = {_stem(p.name): p for p in files}
    superseded_live: list[dict] = []
    dangling: list[dict] = []
    stale: list[dict] = []
    by_title: dict[str, list[Path]] = {}

    # an override or a config value that is not a whole number falls back to
    # the configured (then default) threshold instead of raising
    limit = _threshold(stale_days)
    if limit is None:
        limit = _threshold((getattr(cfg, "governance", None) or {}).get("stale_days")) or 180
    cited = cited if cited is not None else {}
    now = time.time()

    for path in files:
        meta = _frontmatter(path)
        target = ""
        for key in _SUPERSEDED:
            if meta.get(key):
                target = _stem(meta[key])
                break
        if target:
            superseded_live.append({
                "file": path.name, "path": str(path),
                "superseded_by": target,
                "target_exists": target in by_stem,
                "reason": "frontmatter marks this note as replaced",
                "action": "drop it from the index (loci forget) and keep the file "
                          "for history" if target in by_stem
                          else "its replacement is missing — fix the reference first",
            })
        for key in ("supersedes", "supersedes_note"):
            ref = _stem(meta.get(key, "")) if meta.get(key) else ""
            if ref and ref not in by_stem:
                dangling.append({
                    "file": path.name, "path": str(path),
                    "references": ref,
                    "reason": "`supersedes:` points at a note that does not exist",
                    "action": "fix the stem, or add the missing note",
                })

        key = _title(path)
        by_title.setdefault(key, []).append(path)

        try:
            age_days = (now - path.stat().st_mtime) / 86400
        except OSError:
            continue
        src = str(path.resolve())
        entry = cited.get(src) or {}
        never_cited = not entry.get("count")
        if age_days > limit and never_cited:
            stale.append({
                "file": path.name, "path": str(path),
                "age_days": round(age_days, 1),
                "reason": f"unreviewed for {age_days:.0f}d and never cited",
                "action": "confirm it is still true, or retire it",
            })

    duplicate_truth: list[dict] = []
    for title, group in by_title.items():
        if len(group) < 2:
            continue
        hashes = {_hash(p) for p in group}
        if len(hashes) > 1:
            duplicate_truth.append({
                "title": title,
                "files": [p.name for p in group],
                "reason": "same title, different bodies, all still indexed",
                "action": "declare supersedes/effective, or retire the older one",
            })

    findings = {
        "superseded_live": superseded_live,
        "duplicate_truth": duplicate_truth,
        "dangling": dangling,
        "stale": stale,
    }
    findings["total"] = sum(len(v) for v in findings.values())
    findings["scanned"] = len(files)
    return findings


def report(findings: dict) -> str:
    """Human-readable rendering, ordered by how bad the finding is."""
    if findings.get("scanned") == 0:
        return "(no sources configured — nothing to scan)"
    lines: list[str] = []
    ordered = [
        ("superseded_live", "SUPERSEDED BUT STILL INDEXED"),
        ("duplicate_truth", "TWO ACTIVE NOTES, ONE TITLE"),
        ("dangling", "BROKEN SUPERSEDE LINKS"),
        ("stale", "OLD AND NEVER CITED"),
    ]
    for key, heading in ordered:
        rows = findings.get(key) or []
        if not rows:
            continue
        lines.append(f"{heading} ({len(rows)})")
        for row in rows[:20]:
            if key == "duplicate_truth":
                lines.append(f"  {', '.join(row['files'])}")
            else:
                extra = f" -> {row.get('superseded_by') or row.get('references') or ''}"
                lines.append(f"  {row['file']}{extra}")
            lines.append(f"    {row['reason']}; {row['action']}")
        if len(rows) > 20:
            lines.append(f"  ... and {len(rows) - 20} more")
        lines.append("")
    if not lines:
        return (f"scanned {findings['scanned']} note(s): no lifecycle findings.\n"
                "A clean scan means the corpus is consistent, not that it is true —\n"
                "run `loci quality` for whether answers are still good.")
    lines.append(f"scanned {findings['scanned']} note(s), "
                 f"{findings['total']} finding(s).")
    lines.append("Nothing was changed. Retire explicitly: `loci forget` (or "
                 "`brain_forget`), or edit the frontmatter.")
    return "\n".join(lines)
