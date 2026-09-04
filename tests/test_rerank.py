import json

import second_brain.retriever as retriever_module
from second_brain.retriever import rerank_hits


class _Msg:
    def __init__(self, content):
        self.content = content


class _Client:
    """Fake OpenAI client whose reply is fixed per test."""

    reply = "[]"

    def __init__(self, **kw):
        outer = self

        class Completions:
            def create(self, **kwargs):
                class Resp:
                    class choices:
                        pass

                Resp.choices = [type("Choice", (), {"message": _Msg(outer.reply)})()]
                return Resp()

        self.chat = type("C", (), {"completions": Completions()})()


def patch_llm(monkeypatch, reply: str):
    _Client.reply = reply
    monkeypatch.setattr(retriever_module, "OpenAI", _Client)
    return {"base_url": "x", "api_key": "y", "model": "m"}


HITS = [{"id": "a", "text": "weak match", "source": "a.md", "section": "",
         "tags": "", "chunk": 0, "distance": None},
        {"id": "b", "text": "strong match for the query", "source": "b.md",
         "section": "", "tags": "", "chunk": 0, "distance": None}]


def test_rerank_reorders_by_llm_scores(monkeypatch):
    llm = patch_llm(monkeypatch, json.dumps([[0, 0], [1, 3]]))
    out = rerank_hits(llm, "query", HITS)
    assert out[0]["id"] == "b"


def test_rerank_fail_open_on_prose_reply(monkeypatch):
    llm = patch_llm(monkeypatch, "sure, the answer is candidate number one!")
    out = rerank_hits(llm, "query", HITS)
    assert [h["id"] for h in out] == ["a", "b"]  # original order preserved


def test_rerank_fail_open_on_api_error(monkeypatch):
    class Boom:
        def __init__(self, **kw):
            raise RuntimeError("api down")

    monkeypatch.setattr(retriever_module, "OpenAI", Boom)
    out = rerank_hits({"base_url": "x", "api_key": "y", "model": "m"}, "q", HITS)
    assert [h["id"] for h in out] == ["a", "b"]


def test_rerank_skips_single_hit(monkeypatch):
    llm = patch_llm(monkeypatch, json.dumps([[0, 3]]))
    assert rerank_hits(llm, "q", HITS[:1]) == HITS[:1]


def test_rerank_prompt_demands_json_only(monkeypatch):
    seen = {}

    class Probe(_Client):
        def __init__(self, **kw):
            super().__init__(**kw)
            outer = self

            class Completions:
                def create(self, **kwargs):
                    seen["system"] = kwargs["messages"][0]["content"]
                    seen["temperature"] = kwargs.get("temperature")
                    class Resp:
                        pass
                    Resp.choices = [type("Choice", (), {"message": _Msg("[]")})()]
                    return Resp()

            self.chat = type("C", (), {"completions": Completions()})()

    monkeypatch.setattr(retriever_module, "OpenAI", Probe)
    rerank_hits({"base_url": "x", "api_key": "y", "model": "m"}, "q", HITS)
    assert "JSON" in seen["system"]
    assert seen["temperature"] == 0.0


def test_rerank_off_by_default():
    from second_brain import config
    cfg = config.Config()
    for section, values in config.DEFAULTS.items():
        getattr(cfg, section).update(values)
    assert cfg.retrieval["rerank"] is False
