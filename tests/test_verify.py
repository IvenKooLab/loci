import second_brain.retriever as retriever_module
from second_brain.retriever import verify_answer

LLM = {"base_url": "x", "api_key": "y", "model": "m"}

HITS = [{"id": "1", "text": "T8 gives a 43% speedup on drafts", "source": "a.md",
         "section": "Advice", "tags": "", "links": "", "chunk": 0,
         "mtime": 0.0, "distance": None}]


class _FakeOpenAI:
    reply = "[]"
    seen = {}

    def __init__(self, **kw):
        outer = self

        class Completions:
            def create(self, **kwargs):
                _FakeOpenAI.seen.clear()
                _FakeOpenAI.seen.update(kwargs)
                class Resp:
                    pass
                Resp.choices = [type("Choice", (), {
                    "message": type("Msg", (), {"content": outer.reply})()})()]
                return Resp()

        self.chat = type("C", (), {"completions": Completions()})()


def patch(monkeypatch, reply):
    _FakeOpenAI.reply = reply
    _FakeOpenAI.seen.clear()
    monkeypatch.setattr(retriever_module, "OpenAI", _FakeOpenAI)


def test_verify_formats_claims_with_marks(monkeypatch):
    patch(monkeypatch, """[
        {"claim": "T8 gives 43% speedup", "status": "supported", "excerpt": 1},
        {"claim": "T8 works on any GPU", "status": "unsupported", "excerpt": null}
    ]""")
    out = verify_answer(LLM, "q?", "answer text", HITS)
    assert "✓ T8 gives 43% speedup [excerpt 1]" in out
    assert "✗ T8 works on any GPU" in out
    # the header legend carries the status words; claim lines carry only marks
    claim_lines = [l for l in out.splitlines()
                   if l.strip() and not l.strip().startswith(("Claim-by-claim", "  ✓", "~", "✗", "?"))]
    header = [l for l in out.splitlines() if "Claim-by-claim" in l]
    assert header and "✓ supported" in header[0]          # legend explains the marks
    assert all("[excerpt" in l or "T8 works on any GPU" in l for l in claim_lines)


def test_verify_partial_mark(monkeypatch):
    patch(monkeypatch, '[{"claim": "roughly 40%", "status": "partial", "excerpt": 1}]')
    assert "~" in verify_answer(LLM, "q?", "a", HITS)


def test_verify_fail_open_on_prose(monkeypatch):
    patch(monkeypatch, "I cannot produce JSON right now")
    out = verify_answer(LLM, "q?", "a", HITS)
    assert "not audited" in out or "unavailable" in out


def test_verify_fail_open_on_exception(monkeypatch):
    class Boom:
        def __init__(self, **kw):
            raise RuntimeError("down")

    monkeypatch.setattr(retriever_module, "OpenAI", Boom)
    out = verify_answer(LLM, "q?", "a", HITS)
    assert out.startswith("(verification unavailable: RuntimeError")


def test_verify_empty_answer_short_circuits(monkeypatch):
    patch(monkeypatch, "should never be called")
    assert verify_answer(LLM, "q?", "  ", HITS) == "(nothing to verify)"
    assert _FakeOpenAI.seen == {}  # no LLM call was made


def test_verify_prompt_bans_outside_knowledge(monkeypatch):
    patch(monkeypatch, "[]")
    verify_answer(LLM, "q?", "a", HITS)
    system = _FakeOpenAI.seen["messages"][0]["content"]
    assert "outside knowledge" in system
    assert _FakeOpenAI.seen["temperature"] == 0.0
