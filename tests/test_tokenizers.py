"""Tokenizer plugin tests: default CJK single-char vs jieba word-level."""
import pytest

from conftest import build_index, make_cfg, write_corpus
from loci import config
from loci.bm25 import BM25, tokenize
from loci.tokenizers import (default_tokenize, get_tokenizer,
                             jieba_tokenize)


# [1] the default tokenizer keeps the original behavior

def test_default_tokenizer_splits_cjk_single_chars():
    assert tokenize("向量检索") == ["向", "量", "检", "索"]


def test_default_tokenizer_keeps_latin_words():
    assert tokenize("RAG embedding") == ["rag", "embedding"]


def test_tokenize_is_alias_for_default():
    assert tokenize("a b") == default_tokenize("a b")


# [2] jieba tokenizer keeps Chinese words intact

def test_jieba_tokenizer_segments_words():
    pytest.importorskip("jieba")
    toks = jieba_tokenize("向量检索和混合检索的区别")
    assert "向量" in toks and "检索" in toks
    assert "检索" == toks[toks.index("向量") + 1]   # 向量检索 stays one phrase


def test_jieba_tokenizer_keeps_latin_runs():
    pytest.importorskip("jieba")
    toks = jieba_tokenize("embedding 模型选型")
    assert "embedding" in toks and "模型" in toks


# [3] registry lookups and unknown-name handling

def test_get_tokenizer_known_names():
    assert get_tokenizer("default") is default_tokenize
    assert get_tokenizer("jieba") is jieba_tokenize


def test_get_tokenizer_unknown_name_raises():
    with pytest.raises(ValueError):
        get_tokenizer("nope")


# [4] BM25 accepts an injected tokenizer

def test_bm25_accepts_injected_tokenizer():
    corpus = {"a": "向量检索是混合检索的一部分", "b": "向量数据库存储高维向量"}
    bm = BM25(corpus, tokenizer=jieba_tokenize)
    scores = dict(bm.score("混合检索"))
    assert scores.get("a", 0.0) > 0.0
    assert "b" not in scores                     # no word overlap under jieba


def test_bm25_default_is_unchanged():
    corpus = {"a": "向量检索是混合检索的一部分", "b": "向量数据库存储高维向量"}
    bm = BM25(corpus)
    assert bm._tok is default_tokenize           # default behavior preserved
    scores = dict(bm.score("混合检索"))
    assert scores.get("a", 0.0) > 0.0           # single-char overlap still scores


# [5] retriever runs hybrid search end-to-end with the jieba tokenizer

def test_retriever_hybrid_with_jieba_tokenizer(tmp_path):
    pytest.importorskip("jieba")
    sources = write_corpus(tmp_path, {
        "a.md": "# A\n混合检索把向量检索和BM25关键词检索融合起来",
        "b.md": "# B\n完全没有关系的其他内容",
    })
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    retriever.bm25_tokenizer = "jieba"
    hits = retriever.search("混合检索")
    assert hits and hits[0]["source"].replace("\\", "/").endswith("/a.md")


# [6] config validates tokenizer names and warns on unknown values

def test_config_unknown_tokenizer_falls_back(tmp_path, capsys):
    p = tmp_path / "c.toml"
    p.write_text('[bm25]\ntokenizer = "foo"\n[[sources]]\npath = "X"',
                 encoding="utf-8")
    cfg = config.load(str(p))
    assert cfg.bm25["tokenizer"] == "default"
    assert "bm25.tokenizer" in capsys.readouterr().err
