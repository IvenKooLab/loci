"""ChatGPT exports: messages without create_time (or with equal timestamps)
used to all sort to the top in mapping-dict order, scrambling the
conversation. Timestamped turns keep their order; untimed turns keep the
mapping insertion order instead of piling up."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loci.chatlog import parse_chatlog


def _chatgpt_file(tmp_path, mapping):
    p = tmp_path / "conversations.json"
    p.write_text(__import__("json").dumps(
        [{"title": "t", "mapping": mapping}]), encoding="utf-8")
    return p


def test_untimed_messages_keep_mapping_order(tmp_path):
    # every turn untimed (common in filtered/legacy exports): the mapping
    # insertion order used to be random-ish after sorting all-zeros
    mapping = {
        "n1": {"message": {"author": {"role": "user"},
                           "content": {"parts": ["first"]}, "create_time": None}},
        "n2": {"message": {"author": {"role": "assistant"},
                           "content": {"parts": ["second"]}, "create_time": None}},
        "n3": {"message": {"author": {"role": "user"},
                           "content": {"parts": ["third"]}, "create_time": None}},
    }
    convs = parse_chatlog(_chatgpt_file(tmp_path, mapping))
    text = convs[0]["text"]
    assert text.index("first") < text.index("second") < text.index("third")


def test_timed_messages_sort_by_time(tmp_path):
    mapping = {
        "n1": {"message": {"author": {"role": "user"},
                           "content": {"parts": ["late"]}, "create_time": 200}},
        "n2": {"message": {"author": {"role": "assistant"},
                           "content": {"parts": ["early"]}, "create_time": 100}},
    }
    convs = parse_chatlog(_chatgpt_file(tmp_path, mapping))
    assert convs[0]["text"].index("early") < convs[0]["text"].index("late")


def _turn(role, text, ts):
    return {"message": {"author": {"role": role}, "create_time": ts,
                        "content": {"content_type": "text", "parts": [text]}}}


def test_an_untimed_turn_stays_between_its_neighbours(tmp_path):
    """The common mixed export: user turns carry no create_time, assistant
    turns do. Sorting untimed turns as time 0 hoisted both questions above
    both answers — q1 q2 a1 a2 — which reads as one question answered twice."""
    mapping = {
        "n0": _turn("user", "q1", None),
        "n1": _turn("assistant", "a1", 100.0),
        "n2": _turn("user", "q2", None),
        "n3": _turn("assistant", "a2", 200.0),
    }
    text = parse_chatlog(_chatgpt_file(tmp_path, mapping))[0]["text"]
    order = [text.index(w) for w in ("q1", "a1", "q2", "a2")]
    assert order == sorted(order), "turns were reordered"


def test_an_untimed_turn_before_any_timestamped_one_stays_first(tmp_path):
    mapping = {
        "n0": _turn("user", "opening question", None),
        "n1": _turn("assistant", "an answer", 100.0),
        "n2": _turn("assistant", "a later answer", 300.0),
    }
    text = parse_chatlog(_chatgpt_file(tmp_path, mapping))[0]["text"]
    assert text.index("opening question") < text.index("an answer") < text.index("a later answer")


def test_timestamped_turns_are_still_ordered_by_time_when_mixed(tmp_path):
    mapping = {
        "n0": _turn("assistant", "middle", 200.0),
        "n1": _turn("user", "untimed", None),
        "n2": _turn("assistant", "last", 900.0),
        "n3": _turn("assistant", "first", 100.0),
    }
    text = parse_chatlog(_chatgpt_file(tmp_path, mapping))[0]["text"]
    assert text.index("first") < text.index("middle") < text.index("untimed") < text.index("last")
