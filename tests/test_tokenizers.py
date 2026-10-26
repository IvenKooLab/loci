"""Tokenizer plugin tests: the frozen default, plus the opt-in ones."""
import re

import pytest

from conftest import build_index, make_cfg, write_corpus
from loci import config
from loci.bm25 import BM25, tokenize
from loci.tokenizers import (cjk_bigram_tokenize, default_tokenize,
                             get_tokenizer, hyphen_join_tokenize,
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
    assert get_tokenizer("cjk_bigram") is cjk_bigram_tokenize
    assert get_tokenizer("hyphen_join") is hyphen_join_tokenize
    assert get_tokenizer("jieba") is jieba_tokenize


def test_get_tokenizer_unknown_name_raises():
    with pytest.raises(ValueError):
        get_tokenizer("nope")


# [3b] cjk_bigram: phrase matches survive inside longer words, decoys do not


def test_bigram_keeps_phrase_inside_longer_word():
    toks = cjk_bigram_tokenize("全文检索")
    assert "检索" in toks
    assert toks == ["全文", "文检", "检索"]


def test_bigram_does_not_join_across_word_boundaries():
    toks = cjk_bigram_tokenize("定期检查索引")
    assert "检索" not in toks          # 检 and 索 are adjacent but not a word


def test_bigram_keeps_latin_runs_whole():
    assert "embedding" in cjk_bigram_tokenize("embedding 模型选型")


def test_bigram_single_char_run_stays_a_token():
    assert cjk_bigram_tokenize("检") == ["检"]


def test_bigram_ranks_the_real_match_and_drops_the_decoy():
    # the regression that motivated this tokenizer: under single-char CJK the
    # decoy outranks the document that actually contains 检索
    corpus = {"correct": "全文检索是知识库的核心能力",
              "decoy": "定期检查索引状态并重建"}
    single = dict(BM25(corpus).score("检索"))
    assert single["decoy"] > single["correct"]

    bigram = dict(BM25(corpus, tokenizer=cjk_bigram_tokenize).score("检索"))
    assert bigram.get("correct", 0.0) > 0.0
    assert "decoy" not in bigram


def test_bigram_keeps_the_jieba_win():
    # jieba's advertised case must keep working under bigrams
    corpus = {"a": "向量检索是混合检索的一部分", "b": "向量数据库存储高维向量"}
    scores = dict(BM25(corpus, tokenizer=cjk_bigram_tokenize).score("混合检索"))
    assert scores.get("a", 0.0) > 0.0
    assert "b" not in scores


# [3c] default is frozen; the hyphen fix lives in its own tokenizer


def test_default_tokenizer_does_not_join_hyphenates():
    # pinned on purpose: installs that never set [bm25] tokenizer must see the
    # same token stream as v0.8.1, or their rankings move under them
    toks = default_tokenize("Wi-Fi reconnect")
    assert toks == ["wi", "fi", "reconnect"]
    assert "wifi" not in toks


def test_hyphen_join_tokenizer_adds_the_joined_form():
    toks = hyphen_join_tokenize("Wi-Fi reconnect")
    assert "wi" in toks and "fi" in toks
    assert "wifi" in toks               # so a `wifi` query finds "Wi-Fi"


def test_hyphen_join_handles_multi_part_compounds():
    assert "x86_64" not in hyphen_join_tokenize("x86-64 build")
    assert "x8664" in hyphen_join_tokenize("x86-64 build")


def test_bm25_default_still_needs_the_spelling_the_file_uses():
    corpus = {"c": "文档里提到了 Wi-Fi 重连风暴", "d": "其他内容"}
    assert dict(BM25(corpus).score("Wi-Fi")).get("c", 0.0) > 0.0
    assert "c" not in dict(BM25(corpus).score("wifi"))       # unchanged


def test_bm25_hyphen_join_matches_both_spellings():
    corpus = {"c": "文档里提到了 Wi-Fi 重连风暴", "d": "其他内容"}
    bm = BM25(corpus, tokenizer=hyphen_join_tokenize)
    assert dict(bm.score("wifi")).get("c", 0.0) > 0.0
    assert dict(bm.score("Wi-Fi")).get("c", 0.0) > 0.0


def test_default_tokenizer_matches_the_pre_registry_implementation():
    """The exact expression v0.8.1 used, so any future edit to `default` shows
    up here as a diff rather than as silently different search results."""
    original = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
    for text in ["Hello World 123",
                 "Wi-Fi 重连风暴 state-of-the-art",
                 "向量检索 embedding 混合 RAG-2026",
                 "a-b c—d e_f"]:
        assert default_tokenize(text) == original.findall(text.lower()), text


def test_default_tokenizer_leaves_plain_text_alone():
    assert default_tokenize("Hello World 123") == ["hello", "world", "123"]


def test_bigram_also_joins_hyphenates():
    assert "wifi" in cjk_bigram_tokenize("Wi-Fi 重连")


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
