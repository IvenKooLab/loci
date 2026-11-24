"""Nothing but protocol JSON may reach stdout while serving MCP.

The one-time "jieba is not installed" hint was printed to stdout: with
[bm25] tokenizer = "jieba" and the package absent, the first brain_search
of a session wrote a prose line into the stdio protocol stream, which the
host reads as a malformed reply. Diagnostics belong on stderr.
"""
from __future__ import annotations

import sys

from loci import tokenizers


def test_the_missing_jieba_hint_goes_to_stderr(capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "jieba", None)          # as if not installed
    monkeypatch.setattr(tokenizers, "_warned_jieba", False)  # the hint fires once per process

    assert tokenizers.jieba_tokenize("hello world") == ["hello", "world"]

    out, err = capsys.readouterr()
    assert out == "", "prose on stdout corrupts the MCP protocol stream"
    assert "jieba" in err and "loci-rag[zh]" in err
