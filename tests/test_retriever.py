import loci.retriever as retriever_module
from loci.retriever import Retriever, answer

CORPUS = {
    "fox.md": "# Fox facts\nthe quick brown fox jumps over the lazy dog",
    "search.md": "# Search notes\nvector search uses embeddings and cosine similarity",
    "garden.md": "# Garden\n tomatoes and peppers need sun and water",
}


def make(tmp_path, hybrid=True, top_k=3):
    from conftest import build_index, write_corpus
    sources = write_corpus(tmp_path, CORPUS)
    from conftest import make_cfg
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg, hybrid=hybrid)
    retriever.top_k = top_k
    return retriever


def test_hybrid_search_ranks_relevant_first(tmp_path):
    hits = make(tmp_path).search("vector embeddings cosine")
    assert hits[0]["source"].endswith("search.md")
    assert hits[0]["section"] == "Search notes"


def test_hybrid_beats_pure_vector_on_keyword_hit(tmp_path):
    # "jumps" is a rare keyword: hybrid must keep the fox doc at #1 even if
    # the fake embedding would spread mass across docs
    hits = make(tmp_path).search("quick brown fox jumps")
    assert hits[0]["source"].endswith("fox.md")


def test_non_hybrid_path_still_works(tmp_path):
    hits = make(tmp_path, hybrid=False).search("vector embeddings cosine")
    assert hits[0]["source"].endswith("search.md")


def test_tag_filter_narrows_results(tmp_path):
    from conftest import build_index, make_cfg, write_corpus
    files = {"t.md": "---\ntags: [rag]\n---\n# T\nvector search content here",
             "u.md": "# U\nvector search content here too"}
    sources = write_corpus(tmp_path, files)
    cfg = make_cfg(tmp_path, sources)
    _, _, retriever = build_index(cfg)
    retriever.top_k = 5
    unfiltered = retriever.search("vector search content")
    assert len(unfiltered) == 2
    filtered = retriever.search("vector search content", tag="rag")
    assert len(filtered) == 1
    assert filtered[0]["tags"] == "rag"


class FakeCompletions:
    last_messages = None

    def create(self, **kwargs):
        FakeCompletions.last_messages = kwargs["messages"]

        class Msg:
            content = "an answer [source: somewhere]"

        class Choice:
            message = Msg()

        class Resp:
            choices = [Choice()]

        return Resp()


class FakeClient:
    def __init__(self, **kwargs):
        pass

    chat = None


def test_answer_builds_cited_context(monkeypatch):
    class Holder:
        chat = type("C", (), {"completions": type("K", (), {
            "create": staticmethod(lambda **kw: FakeCompletions().create(**kw))})()})

    monkeypatch.setattr(retriever_module, "OpenAI", lambda **kw: Holder())
    hits = [{"text": " excerpt one ", "source": "a.md", "section": "S1"},
            {"text": "excerpt two", "source": "b.md", "section": ""}]
    out = answer({"base_url": "x", "api_key": "y", "model": "m"}, "q?", hits)
    assert out.startswith("an answer")
    msgs = FakeCompletions.last_messages
    assert "a.md | section: S1" in msgs[-1]["content"]
    assert "b.md" in msgs[-1]["content"]
    assert "Question: q?" in msgs[-1]["content"]
    assert "do not invent" in msgs[0]["content"]
