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

import hashlib
import json
import os
import re
import time
from pathlib import Path

from loci import fsutil

MAX_RECORD_BYTES = 256 * 1024   # task snapshots and entity state, not blobs
_MAX_SEGMENT = 80
_HASH_LEN = 12


def _slug(text: str) -> str:
    """Filesystem-safe key segment: keeps CJK and word characters, drops the rest."""
    kept = re.sub(r"[^\w\-.]+", "-", text.strip(), flags=re.UNICODE).strip("-.")
    return kept[:_MAX_SEGMENT] or "unnamed"


def _segment(text) -> str:
    """Collision-proof file-name segment for an exact key.

    `_slug` alone let two different keys share one file — the one thing an
    exact-key store must never do: anything past 80 characters was cut off
    (two long ids with the same prefix), and on case-insensitive volumes
    (Windows, default macOS) `Task-1` and `task-1` ARE one name. Keys fold
    to one case on every platform, and a key too long to keep whole ends in
    a digest of its full form instead of a shared prefix."""
    kept = re.sub(r"[^\w\-.]+", "-", str(text).strip(), flags=re.UNICODE) \
        .strip("-.").casefold()
    if len(kept) > _MAX_SEGMENT:
        kept = (kept[:_MAX_SEGMENT - _HASH_LEN - 1] + "-"
                + hashlib.sha1(kept.encode("utf-8")).hexdigest()[:_HASH_LEN])
    return kept or "unnamed"


def state_dir(cfg) -> Path:
    from loci.config import Config  # avoid a cycle in tests that pass fakes
    base = (cfg.state or {}).get("path", "./state") if not isinstance(cfg, Config) \
        else (cfg.state.get("path", "./state") if cfg.state else "./state")
    return Path(base).expanduser()


def _record_path(cfg, type_: str, key: str) -> Path:
    return state_dir(cfg) / _segment(type_) / f"{_segment(key)}.json"


def _legacy_path(cfg, type_: str, key: str):
    """Where collision-prone `_slug` naming put this record; None when both
    namings agree (a lowercase key that fits — the common case), so there is
    nothing to migrate."""
    old = state_dir(cfg) / _slug(str(type_)) / f"{_slug(str(key))}.json"
    return None if old == _record_path(cfg, type_, key) else old


def _legacy_files(cfg, type_: str, key: str) -> list[Path]:
    """Records the old naming left for this key, newest first.

    The old file name kept the key's original case, so on a case-sensitive
    volume `Order-42.json` is invisible to a lookup spelled `order-42`
    unless the directory is searched by folded name — the legacy path alone
    only ever matched the exact original spelling (Linux CI caught it).
    Newest first: two spellings of one key are one key, and the store's
    contract is last write wins."""
    root = state_dir(cfg)
    want_type, want_key = _slug(str(type_)).casefold(), _slug(str(key)).casefold()
    found: list[Path] = []
    try:
        folders = [d for d in root.iterdir()
                   if d.is_dir() and d.name.casefold() == want_type]
    except OSError:
        return []
    for folder in folders:
        try:
            found += [f for f in folder.iterdir()
                      if f.suffix == ".json" and f.stem.casefold() == want_key]
        except OSError:
            continue

    def age(f: Path):
        try:
            return (f.stat().st_mtime_ns, f.name)
        except OSError:
            return (0, f.name)

    return sorted(found, key=age, reverse=True)


def _existing(cfg, type_: str, key: str) -> Path | None:
    """The file holding this record: its current name, else the legacy one."""
    path = _record_path(cfg, type_, key)
    if path.is_file():
        return path
    old = _legacy_path(cfg, type_, key)
    if old is not None and old.is_file():
        return old
    return next(iter(_legacy_files(cfg, type_, key)), None)


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _fold_dir_name(wanted: Path) -> None:
    """Spell the type directory on disk the way keys are spelled now.

    On a case-insensitive volume an existing `Task/` is the same directory
    as `task/`, so nothing ever renamed it and listings kept showing the
    old spelling."""
    try:
        actual = next((d for d in wanted.parent.iterdir()
                       if d.is_dir() and d.name.casefold() == wanted.name.casefold()), None)
        if actual is not None and actual.name != wanted.name:
            os.rename(actual, wanted)
    except OSError:
        pass                                   # cosmetic: never fail a save over it


def save(cfg, type_: str, key: str, data) -> str:
    """Write one record; last write wins. Returns the file path."""
    if not isinstance(data, (dict, list)):
        raise ValueError("state data must be a JSON object or array")
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if len(blob.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError(f"state record exceeds {MAX_RECORD_BYTES // 1024} KiB — "
                         "store blobs elsewhere and keep a reference here")
    path = _record_path(cfg, type_, key)
    # unique tmp per writer + replace retries on Windows (a concurrent reader
    # holds the target open and the rename fails WinError 5 without them)
    fsutil.atomic_write(path, blob)
    _fold_dir_name(path.parent)
    # a record first saved under the collision-prone name moves with it —
    # unless that name was a truncated one: two long keys shared it, and a
    # save under one cannot prove the old file held that key's data
    if len(_slug(str(key))) < _MAX_SEGMENT:
        for stale in _legacy_files(cfg, type_, key):
            if not _same_file(stale, path):
                try:
                    stale.unlink()
                except OSError:
                    pass
    return str(path)


def get(cfg, type_: str, key: str):
    """One record by exact key, or None. No search, no scoring."""
    path = _existing(cfg, type_, key)
    if path is None:
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
    prefix = _segment(type_prefix) if type_prefix else ""
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
    # newest first; ties (Windows file-clock granularity can merge a burst of
    # saves into one tick) break deterministically by type then key, so the
    # same directory always lists the same way instead of in glob order.
    out.sort(key=lambda r: (-r["mtime"], r["type"], r["key"]))
    return out


def delete(cfg, type_: str, key: str) -> bool:
    """Remove one record. Returns whether it existed."""
    path = _existing(cfg, type_, key)
    if path is not None:
        path.unlink()
        return True
    return False
