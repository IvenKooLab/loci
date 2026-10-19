"""Multi-token role auth: legacy token merge, role ordering, bad tokens."""
from loci.http_api import _auth_table, resolve_auth, allowed


class Cfg:
    http = {"token": ""}
    auth = []


def test_legacy_token_maps_to_admin():
    cfg = Cfg(); cfg.http = {"token": "legacy-secret"}
    entries = _auth_table(cfg)
    assert len(entries) == 1 and entries[0]["role"] == "admin"
    assert allowed(resolve_auth(entries, "Bearer legacy-secret"), "admin")
    assert resolve_auth(entries, "Bearer wrong") is None
    assert resolve_auth(entries, "legacy-secret") is None   # not a Bearer


def test_auth_tokens_table_and_roles():
    cfg = Cfg()
    cfg.auth = [{"token": "t-view", "role": "viewer", "label": "phone"},
                {"token": "t-edit", "role": "editor", "label": "ecs"},
                {"token": "t-admin", "role": "admin", "label": "mac"},
                {"token": "t-bogus-role", "role": "superuser", "label": "x"}]
    entries = _auth_table(cfg)
    assert len(entries) == 4
    assert entries[-1]["role"] == "viewer"       # unknown roles downgrade
    v = resolve_auth(entries, "Bearer t-view")
    e = resolve_auth(entries, "Bearer t-edit")
    a = resolve_auth(entries, "Bearer t-admin")
    assert allowed(v, "read") and not allowed(v, "write") and not allowed(v, "admin")
    assert allowed(e, "read") and allowed(e, "write") and not allowed(e, "admin")
    assert allowed(a, "read") and allowed(a, "write") and allowed(a, "admin")
    assert resolve_auth(entries, "Bearer nope") is None


def test_no_tokens_generates_random_admin():
    entries = _auth_table(Cfg())
    assert len(entries) == 1 and entries[0]["role"] == "admin"
    assert len(entries[0]["token"]) >= 16
