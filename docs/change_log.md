# Change log

## 0.1.1 — 2026-11-11
Production lock-down (no change to the UI or design).

- **Access policy** (`web/access.py`): `DEMO_MODE` (default `true`) gates the
  built-in demo admin login, the login-card demo hint and synthetic seeding;
  `ALLOW_SIGNUP` (default `false`) closes self-service registration;
  `ALLOWED_EMAILS` / `ALLOWED_DOMAINS` restrict who may sign in (password,
  Google SSO or demo). Sessions that fall outside the policy are dropped.
- **Global auth gate**: every page and HTMX action outside the landing,
  auth and static surface now requires a session (several POST actions
  previously did not).
- **API**: `/api/v1/*` reads require a signed-in session or
  `Authorization: Bearer $FASTSME_API_TOKEN` unless `DEMO_MODE` is on.
  Contacts and companies are scoped to the signed-in owner.
- **Ownership**: `contacts.owner_id` and `organizations.owner_id` (idempotent
  boot migration); the Contacts and Organizations pages show only the
  signed-in user's records (plus unowned demo rows in demo mode).
- **Importer** (`importer.py`): idempotent CSV/JSON contact import owned by a
  user, deduped by any email; LinkedIn/website/extra emails kept in a tagged
  note. Token-gated admin endpoints (`FASTCRM_ADMIN_TOKEN`, hidden/404 when
  unset): backup, contact import, account list, account disable.
- `seed.py` refuses to run (it wipes all tables) when `DEMO_MODE` is off.
- Tests: `tests/test_access.py`.
