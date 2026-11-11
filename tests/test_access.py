"""Lock-down behaviour: DEMO_MODE / ALLOW_SIGNUP / ALLOWED_EMAILS, API auth,
owner scoping and the idempotent importer. Synthetic data only."""
from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OWNER = "owner@example.com"
ROWS = [
    {"first_name": "Ada", "last_name": "Example", "primary_email": "ada@example.org",
     "other_emails": "ada.alt@example.net", "company": "Example Org",
     "company_website": "https://example.org", "linkedin_url": "https://www.linkedin.com/in/example",
     "linkedin_confidence": "high"},
    {"first_name": "Bo", "last_name": "Sample", "primary_email": "bo@example.org", "company": "Example Org"},
]


def _fresh(monkeypatch, **env):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("FASTCRM_DB", str(tmp / "crm.sqlite"))
    monkeypatch.setenv("FASTSME_AUTH_DB", str(tmp / "accounts.sqlite"))
    monkeypatch.setenv("BYOK_DB", str(tmp / "byok.sqlite"))
    monkeypatch.setenv("FASTCRM_SECRET", "test-secret")
    for k in ("DEMO_MODE", "ALLOW_SIGNUP", "ALLOWED_EMAILS", "ALLOWED_DOMAINS",
              "FASTSME_API_TOKEN", "FASTCRM_ADMIN_TOKEN", "API_PUBLIC_READS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for m in [m for m in list(sys.modules) if m in ("db", "seed", "importer", "web_app", "byok")
              or m.startswith("web") or m.startswith("byok.")]:
        del sys.modules[m]
    import web_app
    from starlette.testclient import TestClient
    return web_app, TestClient(web_app.app, follow_redirects=False)


@pytest.fixture()
def locked(monkeypatch):
    return _fresh(monkeypatch, DEMO_MODE="false", ALLOW_SIGNUP="false", ALLOWED_EMAILS=OWNER,
                  FASTSME_API_TOKEN="api-token", FASTCRM_ADMIN_TOKEN="admin-token")


def test_api_requires_auth_when_locked(locked):
    _, c = locked
    assert c.get("/api/v1/contacts").status_code == 401
    assert c.get("/api/v1/contacts/1").status_code == 401
    assert c.get("/api/v1/contacts", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/api/v1/contacts", headers={"Authorization": "Bearer api-token"}).status_code == 200
    assert c.get("/api/v1/health").status_code == 200


def test_demo_login_and_signup_closed(locked):
    _, c = locked
    r = c.post("/login", data={"email": "admin@fastcrm.example", "password": "FastCRM2026$"})
    assert r.status_code == 200 and "Invalid" in r.text
    r = c.post("/auth/local/register", data={"email": "random@evil.test", "password": "x" * 12, "name": "R"})
    assert r.status_code == 403
    assert c.get("/contacts").status_code == 303          # pages need a session
    assert c.post("/deals/1/stage", data={"stage": "Won"}).status_code == 401


def test_allowlisted_google_identity_and_owner_scope(locked, monkeypatch):
    web_app, c = locked
    from web import google_auth
    monkeypatch.setattr(google_auth, "enabled", lambda: True)
    monkeypatch.setattr(google_auth, "exchange", lambda req, code: {"email": "intruder@x.test", "name": "I"})
    c.get("/auth/google")
    st = c.get("/auth/google").headers["location"].split("state=")[1].split("&")[0]
    assert "not+authorised" in c.get(f"/auth/google/callback?code=x&state={st}").headers["location"]

    import importer
    stats = importer.import_rows(ROWS, OWNER, "Owner", "t", apply=True)
    assert stats["contacts_inserted"] == 2 and stats["orgs_inserted"] == 1
    again = importer.import_rows(ROWS, OWNER, "Owner", "t", apply=True)
    assert again["contacts_inserted"] == 0 and again["contacts_updated"] == 2 and again["notes_tagged"] == 2

    monkeypatch.setattr(google_auth, "exchange", lambda req, code: {"email": OWNER, "name": "Owner"})
    c.get("/auth/google")
    loc = c.get("/auth/google").headers["location"]
    st = loc.split("state=")[1].split("&")[0]
    assert c.get(f"/auth/google/callback?code=x&state={st}").headers["location"] == "/"
    page = c.get("/contacts")
    assert page.status_code == 200 and "ada@example.org" in page.text
    data = c.get("/api/v1/contacts").json()
    assert data["meta"]["total"] == 2   # only the owner's rows


def test_admin_endpoints(locked):
    _, c = locked
    assert c.post("/api/v1/admin/backup").status_code == 401
    h = {"Authorization": "Bearer admin-token"}
    r = c.post("/api/v1/admin/backup", headers=h)
    assert r.status_code == 200 and Path(r.json()["crm_backup"]).exists()
    r = c.post("/api/v1/admin/import/contacts", headers=h,
               json={"owner_email": OWNER, "rows": ROWS, "tag": "t", "apply": False})
    assert r.json()["contacts_inserted"] == 2 and r.json()["applied"] is False
    assert c.get("/api/v1/admin/accounts", headers=h).json()["policy"]["demo_mode"] is False


def test_demo_defaults_unchanged(monkeypatch):
    _, c = _fresh(monkeypatch)
    assert c.get("/api/v1/contacts").status_code == 200   # public demo reads
    r = c.post("/login", data={"email": "admin@fastcrm.example", "password": "FastCRM2026$"})
    assert r.status_code == 303
    assert c.post("/api/v1/admin/backup").status_code == 404


def test_seed_refuses_without_demo(monkeypatch):
    _fresh(monkeypatch, DEMO_MODE="false")
    import seed
    with pytest.raises(SystemExit):
        seed.build()
