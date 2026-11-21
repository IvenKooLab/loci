"""Filesystem helpers whose correct answer depends on the volume, not the OS.

macOS default APFS is case-preserving but case-insensitive: /Users/a/Notes and
/Users/a/notes are one directory, yet string comparison says otherwise and
`os.path.normcase` is a no-op on POSIX — so path-keyed joins (chunk counts per
source, harness attribution) silently reported 0 for a differently-cased
spelling of a live directory. On case-sensitive volumes the exact segment is
the only candidate, so the same folding is inert there."""
from __future__ import annotations

import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path, PurePath


@lru_cache(maxsize=1024)
def realcase(path: str) -> str:
    """Fold a path to the on-disk casing of the volume that holds it.

    Each segment is resolved against the parent's actual directory listing;
    a case-insensitive unique hit replaces the typed spelling. Unreadable or
    missing ancestors leave the input untouched (never raises — attribution
    must degrade, not crash)."""
    if sys.platform != "darwin":
        return path
    src = PurePath(path)
    built = Path(src.anchor) if src.anchor else Path(".")
    parts = src.parts[1:] if src.anchor else src.parts
    for part in parts:
        if part in (".", ".."):
            built = built / part
            continue
        try:
            names = os.listdir(built)
        except OSError:
            return path
        if part in names:
            built = built / part
            continue
        low = part.casefold()
        candidates = [n for n in names if n.casefold() == low]
        built = built / (candidates[0] if len(candidates) == 1 else part)
    return str(built)


def atomic_write(target: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Stage through a unique tmp name, then replace in one atomic step.

    The tmp name is unique per writer (pid + thread id): two agents saving
    the same key used to stomp each other's staging file. The replace itself
    retries briefly on Windows, where renaming over a file another thread is
    *reading* fails with WinError 5 — POSIX rename is immune, so there the
    first attempt always succeeds. Raises the last PermissionError if the
    collision outlasts the backoff."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f"{target.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding=encoding)
    try:
        for attempt in range(12):
            try:
                tmp.replace(target)
                return
            except PermissionError:
                if attempt == 11:
                    raise
                time.sleep(min(0.005 * 1.6 ** attempt, 0.05))
    finally:
        tmp.unlink(missing_ok=True)
