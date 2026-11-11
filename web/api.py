"""FastCRM API: token- or session-authenticated reads, token-gated writes,
and token-gated admin operations (backup, contact import, account list)."""

import os
import secrets
import sqlite3

from fastapi import Body, HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param

import db
import importer

from . import access
from .api_core import Resource, SQLiteBackend, create_sqlite_api

RESOURCES = (
    Resource("contacts", "contacts", "Contacts", "People associated with customer organisations.", search_fields=("first_name", "last_name", "email", "job_title")),
    Resource("companies", "organizations", "Companies", "Customer and prospect organisation records.", search_fields=("name", "industry", "territory")),
    Resource("leads", "leads", "Leads", "Unqualified and qualified sales leads.", write_fields=("first_name", "last_name", "organization", "email", "mobile", "status", "source", "industry", "territory"), search_fields=("first_name", "last_name", "organization", "email", "status")),
    Resource("opportunities", "deals", "Opportunities", "Pipeline opportunities and their commercial stages.", search_fields=("stage", "source", "industry", "next_step")),
)
OWNED = {"contacts", "organizations"}


def _bearer(request: Request) -> str:
    scheme, value = get_authorization_scheme_param(request.headers.get("Authorization", ""))
    return value if scheme.lower() == "bearer" else ""


def _token_ok(request: Request, env: str) -> bool:
    configured = os.getenv(env, "")
    return bool(configured) and secrets.compare_digest(configured, _bearer(request))


def _session_user(request: Request) -> str | None:
    session = request.scope.get("session") or {}
    user = session.get("user")
    if not user or not access.may_sign_in(user):
        return None
    if not access.demo_mode() and user.lower() == os.getenv("FASTCRM_ADMIN_EMAIL", "admin@fastcrm.example").lower():
        return None
    return user


def _public_reads() -> bool:
    # The open-source demo keeps public reads unless explicitly locked down.
    return access.demo_mode() and os.getenv("API_PUBLIC_READS", "true").lower() not in ("0", "false", "no", "off")


def read_guard(request: Request) -> bool:
    return _public_reads() or _token_ok(request, "FASTSME_API_TOKEN") or bool(_session_user(request))


def row_scope(request: Request, resource: Resource):
    if resource.table not in OWNED or _token_ok(request, "FASTSME_API_TOKEN"):
        return None
    user = _session_user(request)
    if user is None:
        return ("owner_id IS NULL", ()) if _public_reads() else ("1=0", ())
    uid = db.user_id_for(user)
    if access.demo_mode():
        return ("owner_id=? OR owner_id IS NULL", (uid,))
    return ("owner_id=?", (uid,))


backend = SQLiteBackend(db.DB_PATH, RESOURCES, initialize=db.init_schema)
api = create_sqlite_api(
    product="FastCRM", version="1.0.0",
    description="Integration access to FastCRM customer and pipeline data.",
    base_url="https://crm.fastsme.com", backend=backend, resources=RESOURCES,
    read_guard=read_guard, row_scope=row_scope,
    access_note=("**Access model:** reads require a signed-in session or "
                 "`Authorization: Bearer <FASTSME_API_TOKEN>` (the public demo build "
                 "keeps reads open while `DEMO_MODE` is on). Contacts and companies are "
                 "scoped to the signed-in owner. Writes require the bearer token."),
)


# --- admin (token-gated; hidden and 404 unless FASTCRM_ADMIN_TOKEN is set) ---

def _admin(request: Request) -> None:
    if not os.getenv("FASTCRM_ADMIN_TOKEN"):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Not found.", "details": {}})
    if not _token_ok(request, "FASTCRM_ADMIN_TOKEN"):
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Admin token required.", "details": {}},
                            headers={"WWW-Authenticate": "Bearer"})


@api.post("/v1/admin/backup", include_in_schema=False)
def admin_backup(request: Request):
    _admin(request)
    path = db.backup()
    out = {"crm_backup": path,
           "contacts": db.scalar("SELECT COUNT(*) FROM contacts"),
           "organizations": db.scalar("SELECT COUNT(*) FROM organizations")}
    auth_db = os.getenv("FASTSME_AUTH_DB", "")
    if auth_db and os.path.exists(auth_db):
        from pathlib import Path
        target = Path(path).parent / ("accounts-" + Path(path).name)
        src, dst = sqlite3.connect(auth_db), sqlite3.connect(str(target))
        with dst:
            src.backup(dst)
        src.close(); dst.close()
        out["accounts_backup"] = str(target)
    return out


@api.post("/v1/admin/import/contacts", include_in_schema=False)
def admin_import_contacts(request: Request, payload: dict = Body(...)):
    _admin(request)
    owner = (payload.get("owner_email") or "").strip().lower()
    if not owner or not isinstance(payload.get("rows"), list):
        raise HTTPException(status_code=422, detail={"code": "invalid", "message": "owner_email and rows are required.", "details": {}})
    return importer.import_rows(payload["rows"], owner, payload.get("owner_name", ""),
                                payload.get("tag") or "import", bool(payload.get("apply")))


@api.get("/v1/admin/accounts", include_in_schema=False)
def admin_accounts(request: Request):
    _admin(request)
    from . import account_auth
    with account_auth.accounts._db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,email,name,is_verified,google_linked,(password_hash IS NOT NULL) has_password,"
            "created_at,updated_at FROM accounts ORDER BY id")]
    users = db.rows("SELECT id,name,email FROM users ORDER BY id")
    return {"accounts": rows, "crm_users": users,
            "policy": {"demo_mode": access.demo_mode(), "signup_open": access.signup_open(),
                       "allowlist_active": access.allowlist_active()}}


@api.post("/v1/admin/accounts/disable", include_in_schema=False)
def admin_disable_account(request: Request, payload: dict = Body(...)):
    """Remove an account's password and verification (it can no longer sign in)."""
    _admin(request)
    email = (payload.get("email") or "").strip().lower()
    from . import account_auth
    with account_auth.accounts._db() as conn:
        n = conn.execute("UPDATE accounts SET password_hash=NULL,is_verified=0,google_linked=0 WHERE email=?", (email,)).rowcount
    return {"disabled": n, "email": email}
