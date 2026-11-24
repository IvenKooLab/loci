"""write_memory crashed with AttributeError when tags contained non-string
items (HTTP /remember and /memory pass user JSON straight through):
tags=["a", 123] killed the whole note write."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci.loaders import parse_frontmatter
from loci.memories import write_memory


def test_non_string_tags_are_coerced(tmp_path):
    p = write_memory(str(tmp_path), "body", title="t",
                     tags=["a", 123, None, {"x": 1}, ""])
    meta, _ = parse_frontmatter(Path(p).read_text(encoding="utf-8"))
    # 123 → "123", the dict → its text, None and "" dropped — and the list
    # still parses: a value with braces and colons is quoted on disk now
    # (the test used to pin the bare `{'x': 1}` spelling, which is not a
    # plain YAML scalar)
    assert meta["tags"] == ["memory", "a", "123", "{'x': 1}"]
