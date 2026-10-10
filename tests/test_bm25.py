from loci.bm25 import BM25, tokenize


def test_tokenize_latin_and_cjk():
    assert tokenize("Hello World 123") == ["hello", "world", "123"]
    tokens = tokenize("向量检索 embedding")
    assert "embedding" in tokens
    assert "向" in tokens and "量" in tokens and "检" in tokens and "索" in tokens


def test_relevant_document_ranks_first():
    corpus = {
        "a": "the quick brown fox jumps over the lazy dog",
        "b": "vector embeddings for semantic search",
        "c": "gardening tips for tomatoes and peppers",
    }
    results = BM25(corpus).score("vector semantic search")
    assert results[0][0] == "b"


def test_chinese_query_ranks_chinese_document_first():
    corpus = {
        "cn": "向量数据库支持混合检索与重排序",
        "en": "the database supports hybrid search",
    }
    results = BM25(corpus).score("混合检索")
    assert results[0][0] == "cn"


def test_no_match_returns_empty():
    corpus = {"a": "apples and oranges"}
    assert BM25(corpus).score("quantum physics") == []


def test_empty_corpus_returns_empty():
    assert BM25({}).score("anything") == []


def test_scores_sorted_descending():
    corpus = {
        "weak": "search mentioned once",
        "strong": "search search search search semantic search ranking",
    }
    results = BM25(corpus).score("search")
    assert [k for k, _ in results] == ["strong", "weak"]
