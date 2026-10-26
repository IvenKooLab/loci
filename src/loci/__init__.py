"""loci: Q&A over your personal knowledge base."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _detect_version() -> str:
    """Installed metadata first — that is what `pip install -U` actually
    changes, and therefore the only source worth showing a user. A source
    checkout that was never installed falls back to the version declared in
    pyproject.toml, so development runs report the real number instead of a
    placeholder.

    This is the only place the version is *read* at runtime; pyproject.toml
    stays the only place it is *declared*. Bump that one and both agree.
    """
    try:
        return _pkg_version("loci-rag")
    except PackageNotFoundError:
        pass
    root = Path(__file__).resolve().parents[2]
    try:
        import tomllib
        declared = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(declared["project"]["version"])
    except Exception:                     # not a source tree either
        return "0.0.0+source"


__version__ = _detect_version()
