"""Auth table robustness.

One malformed [[auth.tokens]] entry crashed serve-http at startup
(_auth_table called .get() on it), and a non-ASCII bearer token made
secrets.compare_digest raise TypeError — compare_digest refuses non-ASCII
*strings*; it wants bytes. Any client could trigger that with one header,
and a non-ASCII token in the config broke every authenticated request.
"""
from __future__ import annotations

import pytest

from loci.http_api import _auth_table, resolve_auth
from types import SimpleNamespace


def _cfg(auth, legacy=""):
    return SimpleNamespace(auth=auth, http={"token": legacy})


def test_entries_that_are_not_tables_or_tokens_are_skipped_not_fatal(capsys):
    entries = _auth_table(_cfg([7, None, 3.5, {"token": "good", "role": "viewer", "label": "ok"}]))
    assert [e["token"] for e in entries] == ["good"]
    assert "auth" in capsys.readouterr().err


def test_a_list_of_bare_strings_is_a_list_of_tokens():
    entries = _auth_table(_cfg(["first", "second"]))
    assert [e["token"] for e in entries] == ["first", "second"]
    assert all(e["role"] == "viewer" for e in entries)     # least privilege by default


def test_a_label_of_none_is_unnamed_not_the_string_none():
    entries = _auth_table(_cfg([{"token": "t", "label": None}]))
    assert entries[0]["label"] == "unnamed"


def test_a_bare_string_of_tokens_is_one_token():
    entries = _auth_table(_cfg("secret"))
    assert [e["token"] for e in entries] == ["secret"]


def test_a_token_that_is_not_a_string_is_skipped():
    entries = _auth_table(_cfg([{"token": 12345, "role": "admin"}]))
    assert entries == [] or entries[0]["label"] == "auto-generated"


def test_a_legacy_token_that_is_not_a_string_is_coerced():
    entries = _auth_table(_cfg([], legacy=12345))
    assert entries[0]["token"] == "12345" and entries[0]["role"] == "admin"


def test_a_non_ascii_bearer_header_is_simply_unrecognized():
    entries = [{"token": "abc123", "role": "admin", "label": "t"}]
    assert resolve_auth(entries, "Bearer é") is None
    assert resolve_auth(entries, "Bearer 中文") is None


def test_a_non_ascii_token_in_the_config_still_authenticates():
    entries = [{"token": "中文令牌", "role": "admin", "label": "t"}]
    assert resolve_auth(entries, "Bearer 中文令牌")["label"] == "t"
    assert resolve_auth(entries, "Bearer 中文令牌x") is None
    assert resolve_auth(entries, "Bearer other") is None
