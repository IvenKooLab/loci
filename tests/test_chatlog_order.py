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
