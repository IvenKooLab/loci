"""cmd_bench died on the first malformed line of a cases file (a hand-edited
jsonl with one typo made the whole benchmark unusable)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_bench_skips_malformed_case_lines(tmp_path, capsys):
    from loci.cli import cmd_bench
    from conftest import FakeEmbedder, make_cfg, write_corpus
    from loci.store import Store
    import loci.cli as cli

    cfg = make_cfg(tmp_path, write_corpus(tmp_path, {"a.md": "# A\nsensor alpha"}))
    store = Store(cfg.store["path"])
    monkeybuild = lambda c: (FakeEmbedder(), store)
    cli.build = monkeybuild

    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        '{"query": "sensor", "expect": "a.md"}\n'
        'not json at all\n'
        '{"query": "q2"}\n'
        '{"expect": "y"}\n', encoding="utf-8")

    cmd_bench(cfg, str(cases))
    out = capsys.readouterr().out
    assert out.count("[warn]") == 3               # 3 bad lines skipped with a pointer
    assert "hybrid" in out                        # the valid case still ran
