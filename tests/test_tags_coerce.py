"""write_memory crashed with AttributeError when tags contained non-string
items (HTTP /remember and /memory pass user JSON straight through):
tags=["a", 123] killed the whole note write."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci.memories import write_memory


def test_non_string_tags_are_coerced(tmp_path):
    p = write_memory(str(tmp_path), "body", title="t",
                     tags=["a", 123, None, {"x": 1}, ""])
    text = Path(p).read_text(encoding="utf-8")
    assert "tags: [memory, a, 123, {'x': 1}]" in text
