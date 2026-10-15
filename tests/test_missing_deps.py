"""Optional-dependency UX: files needing a missing extra are skipped with a
clear one-time install hint instead of vanishing silently."""
import sys

import pytest

import loci.loaders as loaders


# [1] pdf/docx files with no optional extra installed

def test_missing_pdf_extra_warns_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loaders, "HAS_PDF", False)
    monkeypatch.setattr(loaders, "HAS_PDF_TABLES", False)
    monkeypatch.setattr(loaders, "_warned_missing", set())
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    assert loaders.scan_sources([{"path": str(tmp_path)}]) == []
    out = capsys.readouterr().out
    assert out.count("[warn] pdf sources") == 1        # once per run, not per file
    assert "pip install 'loci-rag[pdf]'" in out


def test_missing_docx_extra_warns_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loaders, "HAS_DOCX", False)
    monkeypatch.setattr(loaders, "_warned_missing", set())
    (tmp_path / "a.docx").write_bytes(b"PK fake")
    assert loaders.scan_sources([{"path": str(tmp_path)}]) == []
    out = capsys.readouterr().out
    assert "[warn] docx sources" in out
    assert "pip install 'loci-rag[docx]'" in out


def test_installed_extra_produces_no_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loaders, "_warned_missing", set())
    assert loaders.scan_sources([{"path": str(tmp_path)}]) == []
    assert "[warn] pdf sources" not in capsys.readouterr().out


# [2] jieba selected in config but not installed

def test_jieba_missing_warns_once_and_falls_back(monkeypatch, capsys):
    from loci import tokenizers
    monkeypatch.setitem(sys.modules, "jieba", None)     # force ImportError
    monkeypatch.setattr(tokenizers, "_warned_jieba", False)
    out1 = tokenizers.jieba_tokenize("向量检索")
    out2 = tokenizers.jieba_tokenize("向量检索")        # second call: no repeat
    err = capsys.readouterr().out
    assert out1 == tokenizers.default_tokenize("向量检索")   # fail-open fallback
    assert out2 == out1
    assert err.count("loci-rag[zh]") == 1
