"""Document loading: recursively scan directories for .md/.txt (and .pdf when
the optional pypdf package is installed), peeling off Obsidian-style YAML
frontmatter (tags/aliases subset) and collecting [[wikilinks]]."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

try:
    from pypdf import PdfReader
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

SUFFIXES = {".md", ".txt"}
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def extract_wikilinks(body: str) -> str:
    """Collect [[wikilink]] targets as a comma-joined string (deduplicated)."""
    seen: list[str] = []
    for m in _WIKILINK.finditer(body):
        target = m.group(1).strip()
        if target and target.lower() not in (t.lower() for t in seen):
            seen.append(target)
    return ",".join(seen)


def file_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse a minimal YAML subset from leading --- fences: scalars and lists.
    Returns ({meta}, body); malformed fences are left in the body untouched."""
    if not content.startswith("---"):
        return {}, content
    lines = content.splitlines()
    if lines[0].strip() != "---":
        return {}, content
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, content
    meta: dict = {}
    current_list: str | None = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list:
            meta[current_list].append(stripped[2:].strip().strip('"\''))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        current_list = None
        if not value:
            meta[key] = []
            current_list = key
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [v.strip().strip("\"'") for v in inner.split(",")] if inner else []
        else:
            meta[key] = value.strip("\"'")
    return meta, "\n".join(lines[end + 1:])


def tags_of(meta: dict) -> str:
    """Normalize the frontmatter `tags` key (list or string) to a comma-joined string."""
    raw = meta.get("tags", [])
    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",")]
    else:
        items = [str(t).strip() for t in raw]
    return ",".join(t for t in items if t)


def _read_text(p: Path) -> str | None:
    """Read a document as text; returns None when it can't be handled."""
    suffix = p.suffix.lower()
    if suffix in SUFFIXES:
        try:
            return p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"[warn] not UTF-8, skipping: {p.name}")
            return None
    if suffix == ".pdf":
        if not HAS_PDF:
            return None  # silently skip; `doctor` mentions the optional extra
        try:
            reader = PdfReader(str(p))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:
            print(f"[warn] pdf unreadable, skipping: {p.name} ({e})")
            return None
    return None


def scan_sources(sources: list[dict]) -> list[dict]:
    """Return [{path, content, hash, tags, links}] with absolute path strings."""
    docs, seen = [], set()
    for src in sources:
        root = Path(src["path"]).expanduser()
        if not root.exists():
            print(f"[warn] directory not found, skipping: {root}")
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            suffix = p.suffix.lower()
            if suffix not in SUFFIXES and suffix != ".pdf":
                continue
            ap = str(p.resolve())
            if ap in seen:
                continue
            seen.add(ap)
            text = _read_text(p)
            if text is None or not text.strip():
                continue
            meta, body = parse_frontmatter(text)
            docs.append({"path": ap, "content": body, "hash": file_hash(text),
                         "tags": tags_of(meta), "links": extract_wikilinks(body)})
    return docs
