"""BYOK module tests — store, gate policy, routing, and app wiring.

No network or real API keys: the LangChain model build is monkeypatched, and a
throwaway SQLite file backs the store.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def byok(monkeypatch):
    # Fresh DB + deterministic encryption key + small free limit per test run.
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    monkeypatch.setenv("BYOK_DB", tmp.name)
    monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "unit-test-passphrase")
    monkeypatch.setenv("BYOK_FREE_QUERY_LIMIT", "5")
    monkeypatch.setenv("MODEL_PROVIDER", "xai")
    monkeypatch.setenv("XAI_API_KEY", "house-key-123")

    # Import fresh so module-level FREE_LIMIT / DB_PATH pick up the env above.
    for m in [m for m in list(sys.modules) if m == "byok" or m.startswith("byok.")]:
        del sys.modules[m]
    import byok
    import byok.gate as gate
    import byok.store as store
    # build_chat_model must not hit the network — stub it with a marker object.
    monkeypatch.setattr(byok.llm, "build_chat_model",
                        lambda provider, api_key, model=None, **kw: ("MODEL", provider, api_key))
    monkeypatch.setattr(gate._llm, "build_chat_model",
                        lambda provider, api_key, model=None, **kw: ("MODEL", provider, api_key))
    assert gate.FREE_LIMIT == 5
    yield byok
    os.unlink(tmp.name)


def test_store_roundtrip_encrypts(byok):
    from byok import store
    store.set_key("org1", "openai", "sk-secret", "gpt-4o")
    rec = store.get_record("org1")
    assert rec["api_key_enc"] and rec["api_key_enc"] != "sk-secret"  # encrypted at rest
    prov, key, model = store.get_key("org1")
    assert (prov, key, model) == ("openai", "sk-secret", "gpt-4o")
    store.clear_key("org1")
    assert store.get_key("org1") is None


def test_free_tier_then_limit(byok):
    sess = {"user": "a@b.com"}  # no suite_identity -> org falls back to email

    # First 5 queries: allowed on the house key, each commit increments.
    for i in range(5):
        g = byok.begin_query(sess)
        assert not g.blocked and g.reason == "free", f"query {i} should be free"
        g.commit()

    # 6th: blocked with the BYOK prompt.
    g = byok.begin_query(sess)
    assert g.blocked and g.reason == "limit"
    assert "/byok" in g.gate_markdown


def test_byok_key_is_unlimited_and_uncounted(byok):
    from byok import store
    sess = {"user": "a@b.com"}
    store.set_key("a@b.com", "anthropic", "sk-ant", None)

    for _ in range(20):
        g = byok.begin_query(sess)
        assert not g.blocked and g.reason == "byok" and g.used_byok
        assert g.llm == ("MODEL", "anthropic", "sk-ant")
        g.commit()  # must be a no-op for BYOK

    assert store.free_used("a@b.com") == 0


def test_no_house_key_blocks(byok, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    g = byok.begin_query({"user": "x@y.com"})
    assert g.blocked and g.reason == "no_house_key"
    assert "/byok" in g.gate_markdown


def test_no_identity_blocks(byok):
    g = byok.begin_query({})
    assert g.blocked and g.reason == "no_identity"


def test_org_scope_shared_across_users(byok):
    # Two users in the same org share the quota via suite_identity.org_id.
    s1 = {"user": "u1@acme.com", "suite_identity": {"org_id": "acme"}}
    s2 = {"user": "u2@acme.com", "suite_identity": {"org_id": "acme"}}
    for _ in range(3):
        byok.begin_query(s1).commit()
    for _ in range(2):
        byok.begin_query(s2).commit()
    # 5 consumed org-wide -> next is blocked for either user.
    assert byok.begin_query(s2).blocked
    assert byok.begin_query(s1).blocked


def test_usage_helper(byok):
    sess = {"user": "a@b.com"}
    byok.begin_query(sess).commit()
    used, limit, has, prov = byok.usage(sess)
    assert (used, limit, has) == (1, 5, False)
