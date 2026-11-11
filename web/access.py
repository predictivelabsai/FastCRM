"""Deployment access policy: demo mode, sign-up, and the sign-in allow-list.

Env flags (all optional; defaults keep the open-source quickstart working):

- ``DEMO_MODE``      — ``true`` (default) enables the built-in demo admin login
  and first-boot synthetic seeding. Set ``false`` for any real deployment.
- ``ALLOW_SIGNUP``   — ``false`` (default) closes self-service email
  registration. Addresses on the allow-list may still register.
- ``ALLOWED_EMAILS`` / ``ALLOWED_DOMAINS`` — comma-separated. When either is
  set, only matching accounts may sign in (password, Google or demo).
"""
from __future__ import annotations

import os

_FALSE = {"0", "false", "no", "off", ""}


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in _FALSE


def _csv(name: str) -> set[str]:
    return {x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()}


def demo_mode() -> bool:
    return _flag("DEMO_MODE", "true")


def signup_open() -> bool:
    return _flag("ALLOW_SIGNUP", "false")


def allowlist_active() -> bool:
    return bool(_csv("ALLOWED_EMAILS") or _csv("ALLOWED_DOMAINS"))


def on_allowlist(email: str | None) -> bool:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False
    return email in _csv("ALLOWED_EMAILS") or email.rsplit("@", 1)[-1] in _csv("ALLOWED_DOMAINS")


def may_sign_in(email: str | None) -> bool:
    """True if this identity may hold a session under the current policy."""
    email = (email or "").strip().lower()
    if not email:
        return False
    if allowlist_active():
        return on_allowlist(email)
    return True


def may_register(email: str | None) -> bool:
    return on_allowlist(email) if not signup_open() else may_sign_in(email)
