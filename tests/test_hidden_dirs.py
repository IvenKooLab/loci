"""Hidden directories are machinery, not notes (found on macOS, true
everywhere): pathlib globs happily match dotfiles, so without an explicit cut
`scan_sources` indexed `.trash/` — resurrecting every note `brain_forget` ever
soft-deleted — plus `.git` and `.obsidian` internals."""
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
