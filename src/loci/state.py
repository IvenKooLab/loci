"""Exact-key structured state — the complement to semantic memory.

`brain_remember` writes free text and recall goes through hybrid retrieval,
which is right for "what do I know about X". Task-oriented callers need the
other thing: "give me task 8f3c's snapshot" — an exact fetch where semantic
search would be diluted by irrelevant-but-similar conversation. Industry
practice for task state is keyed retrieval, not vectors.

Records are plain JSON files under the instance's `state/` directory
(`state/<type>/<key>.json`): hand-editable, greppable, and deliberately **not
indexed** — putting them in the vector store is the misuse this module exists
to prevent. Real-time dialogue slots belong in the orchestrator's session;
these are for state worth persisting across sessions.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

MAX_RECORD_BYTES = 256 * 1024   # task snapshots and entity state, not blobs


def _slug(text: str) -> str:
    """Filesystem-safe key segment: keeps CJK and word characters, drops the rest."""
    kept = re.sub(r"[^\w\-.]+", "-", text.strip(), flags=re.UNICODE).strip("-.")
    return kept[:80] or "unnamed"


def state_dir(cfg) -> Path:
    from loci.config import Config  # avoid a cycle in tests that pass fakes
    base = (cfg.state or {}).get("path", "./state") if not isinstance(cfg, Config) \
        else (cfg.state.get("path", "./state") if cfg.state else "./state")
    return Path(base).expanduser()


def _record_path(cfg, type_: str, key: str) -> Path:
    return state_dir(cfg) / _slug(type_) / f"{_slug(key)}.json"


def save(cfg, type_: str, key: str, data) -> str:
    """Write one record; last write wins. Returns the file path."""
    if not isinstance(data, (dict, list)):
        raise ValueError("state data must be a JSON object or array")
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if len(blob.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError(f"state record exceeds {MAX_RECORD_BYTES // 1024} KiB — "
                         "store blobs elsewhere and keep a reference here")
    path = _record_path(cfg, type_, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(path)                      # atomic; overwrites on Windows too
    return str(path)


def get(cfg, type_: str, key: str):
    """One record by exact key, or None. No search, no scoring."""
    path = _record_path(cfg, type_, key)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None                        # corrupt record reads as absent


def list_records(cfg, type_prefix: str = "") -> list[dict]:
    """All records (optionally under a type prefix), newest first."""
    root = state_dir(cfg)
    if not root.is_dir():
        return []
    prefix = _slug(type_prefix) if type_prefix else ""
    out: list[dict] = []
    for path in root.glob("*/*.json"):
        if prefix and not path.parent.name.startswith(prefix):
            continue
        try:
            stat = path.stat()
            out.append({
                "type": path.parent.name,
                "key": path.stem,
                "mtime": stat.st_mtime,
                "bytes": stat.st_size,
            })
        except OSError:
            continue
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out


def delete(cfg, type_: str, key: str) -> bool:
    """Remove one record. Returns whether it existed."""
    path = _record_path(cfg, type_, key)
    if path.is_file():
        path.unlink()
        return True
    return False
