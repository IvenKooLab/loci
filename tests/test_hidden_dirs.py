"""Hidden directories are machinery, not notes (found on macOS, true
everywhere): pathlib globs happily match dotfiles, so without an explicit cut
`scan_sources` indexed `.trash/` — resurrecting every note `brain_forget` ever
soft-deleted — plus `.git` and `.obsidian` internals."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci import loaders


def _mk(p: Path, text: str = "note body"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_hidden_dirs_are_not_scanned(tmp_path):
    _mk(tmp_path / "real.md")
    _mk(tmp_path / "sub/nested.md")
    for hidden in (".trash", ".git", ".obsidian/plugins/x", ".venv/lib"):
        _mk(tmp_path / hidden / "machine.md")

    docs = loaders.scan_sources([{"path": str(tmp_path)}])
    paths = {Path(d["path"]).relative_to(tmp_path).as_posix() for d in docs}
    assert paths == {"real.md", "sub/nested.md"}


def test_trashed_memories_stay_forgotten(tmp_path):
    """The concrete symptom: forget moves a note to memories/.trash; the
    memories dir is a source, so the next ingest must not index it back."""
    mem = tmp_path / "memories"
    _mk(mem / "keep.md")
    _mk(mem / ".trash" / "deleted.md")

    docs = loaders.scan_sources([{"path": str(mem)}])
    names = {Path(d["path"]).name for d in docs}
    assert "deleted.md" not in names
    assert "keep.md" in names


def test_hidden_file_itself_is_kept_scannable(tmp_path):
    """The cut is on hidden *directories*; a dot-prefixed file in a visible
    directory (e.g. `.hidden.md`) stays the user's call, not ours."""
    _mk(tmp_path / ".hidden.md")
    docs = loaders.scan_sources([{"path": str(tmp_path)}])
    assert len(docs) == 1


def test_appledouble_sidecars_are_not_scanned(tmp_path):
    """`._foo.md` is macOS's resource-fork sidecar (appears when a bundle
    crosses an exFAT/network volume): binary, would decode into NUL-laced
    garbage chunks on every ingest."""
    (tmp_path / "real.md").write_text("real note", encoding="utf-8")
    (tmp_path / "._real.md").write_bytes(b"\x00\x05\x16AppleDouble\x00binary")
    (tmp_path / "._side.md").write_bytes(b"\x00junk")

    docs = loaders.scan_sources([{"path": str(tmp_path)}])
    names = {Path(d["path"]).name for d in docs}
    assert names == {"real.md"}


def test_find_memories_skips_sidecars(tmp_path):
    from loci.memories import find_memories
    (tmp_path / "keep.md").write_text("has needle", encoding="utf-8")
    (tmp_path / "._keep.md").write_bytes(b"\x00needle\x00")
    hits = find_memories(str(tmp_path), "needle")
    assert [p.name for p in hits] == ["keep.md"]


def test_tcc_denied_source_warns_instead_of_silent_empty(tmp_path, monkeypatch, capsys):
    """macOS TCC (~/Documents without Full Disk Access) makes os.listdir raise
    PermissionError while pathlib rglob stays silent — an empty-looking source.
    The probe must turn that into an actionable warning."""
    (tmp_path / "real.md").write_text("note", encoding="utf-8")
    real_listdir = os.listdir

    def denied(path):
        if str(path) == str(tmp_path):
            raise PermissionError(1, "Operation not permitted")
        return real_listdir(path)

    monkeypatch.setattr(loaders.os, "listdir", denied)
    docs = loaders.scan_sources([{"path": str(tmp_path)}])
    out = capsys.readouterr().out
    assert docs == []
    assert "permission denied" in out
    if sys.platform == "darwin":          # CI on Linux gets the chmod hint
        assert "Full Disk Access" in out


def test_ascii_container_output_survives_cjk_and_emoji():
    """A C-locale container (docker without LANG) gives stdout encoding
    'ascii' — CJK harness names and emoji icons used to crash mid-print.
    The guard must cover ascii streams too, not just Windows code pages."""
    import io
    import sys as _sys
    from loci.cli import _tolerant_output
    buf, keep = io.BytesIO(), _sys.stdout
    stream = io.TextIOWrapper(buf, encoding="ascii")
    _sys.stdout = stream
    try:
        _tolerant_output()
        print("harness 摘要 🧠 ⚡")           # must not raise
        stream.flush()
    finally:
        _sys.stdout = keep
    assert b"\\U0001f9e0" in buf.getvalue()   # degraded, not crashed
