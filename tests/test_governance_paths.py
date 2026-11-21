"""governance._paths used raw rglob("*.md"): it reported .trash notes as
live candidates, counted AppleDouble sidecars as duplicate-truth evidence,
and skipped .MD files on case-insensitive volumes — the same discovery rules
scan_sources had already fixed, applied here too."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import loci.config as config
from loci import governance


def _cfg_for(tmp_path):
    cfg = config.Config()
    for section, values in config.DEFAULTS.items():
        getattr(cfg, section).update(values)
    cfg.sources = [{"path": str(tmp_path)}]
    return cfg


def test_governance_paths_skip_noise(tmp_path):
    cfg = _cfg_for(tmp_path)
    (tmp_path / "live.md").write_text("---\ntitle: live\n---\nbody", encoding="utf-8")
    (tmp_path / ".trash").mkdir()
    (tmp_path / ".trash" / "retired.md").write_text("---\ntitle: old\n---\n", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "plugin.md").write_text("config", encoding="utf-8")
    (tmp_path / "._live.md").write_bytes(b"\x00junk")
    (tmp_path / "UPPER.MD").write_text("---\ntitle: upper\n---\nbody", encoding="utf-8")

    names = sorted(Path(p).name for p in governance._paths(cfg))
    assert names == ["UPPER.MD", "live.md"]   # sorted; case-insensitive volume order
