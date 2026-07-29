"""FastCRM — an open-source sales CRM built with FastHTML.

A server-side, HTMX-driven port of the core of Frappe CRM: leads, a Kanban
deal pipeline, contacts, organizations, tasks, an activity timeline, and an
AI assistant grounded in the live (synthetic) data.

Run:
    python web_app.py            # http://localhost:5006

Login: admin@fastcrm.example / FastCRM2026$  (override via .env, see .env.sample)
"""
from __future__ import annotations

import os
import secrets
import uuid
import logging

from dotenv import load_dotenv
load_dotenv()

from fasthtml.common import (
    fast_app, serve, Div, H1, P, A, Form, Input, Button, Span,
    NotStr, RedirectResponse, Script, Style, Link, Title,
)
from starlette.responses import StreamingResponse, Response

import db
from web.layout import page, LAYOUT_CSS
from web import views, ai
from web.landing import landing_page
from web import google_auth

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("fastcrm")

VALID_EMAIL = os.getenv("FASTCRM_ADMIN_EMAIL", "admin@fastcrm.example")
VALID_PASSWORD = os.getenv("FASTCRM_ADMIN_PASSWORD", "FastCRM2026$")
ENV_LABEL = os.getenv("FASTCRM_ENV_LABEL", "FastCRM")
SECRET = os.getenv("FASTCRM_SECRET", secrets.token_hex(32))
PORT = int(os.getenv("FASTCRM_PORT", "5006"))

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, hdrs=[Style(LAYOUT_CSS)])


# --- auth helpers -----------------------------------------------------------

def _user(session) -> str | None:
    return session.get("user")


def _thread(session) -> str:
    if "thread" not in session:
        session["thread"] = uuid.uuid4().hex
    return session["thread"]


def _guard(session, active: str, builder):
    """Render a page if logged in, else redirect to /login."""
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    content = builder() if callable(builder) else builder
    if not isinstance(content, tuple):
        content = (content,)
    return page(active, ENV_LABEL, _user(session), _thread(session), *content)


def _login_card(error: str = "", email: str = ""):
    return Title("FastCRM — Sign in"), Style(LAYOUT_CSS), Div(
        Form(
            H1("FastCRM"),
            P("Sign in to your sales cockpit"),
            Input(name="email", type="email", placeholder="Email", value=email, required=True),
            Input(name="password", type="password", placeholder="Password", required=True),
            P(error, cls="error") if error else None,
            Button("Sign in", cls="btn primary", type="submit"),
            P(NotStr("Demo: <code>admin@fastcrm.example</code> / <code>FastCRM2026$</code>"), cls="hint"),
            method="post", action="/login", cls="login-card",
        ),
        cls="login-wrap",
    )


# --- auth routes ------------------------------------------------------------

@rt("/login")
def get(session):
    if _user(session):
        return RedirectResponse("/", status_code=303)
    return _login_card()


@rt("/login")
def post(session, email: str = "", password: str = ""):
    if email.strip().lower() == VALID_EMAIL.lower() and password == VALID_PASSWORD:
        session["user"] = email.strip().lower()
        return RedirectResponse("/", status_code=303)
    return _login_card("Invalid email or password.", email)



@rt("/auth/google")
def google_start(session, request):
    if not google_auth.enabled():
        return RedirectResponse("/login?error=Google+sign-in+is+not+configured", status_code=303)
    state = google_auth.new_state()
    session["google_oauth_state"] = state
    return RedirectResponse(google_auth.authorize_url(request, state), status_code=303)


@rt("/auth/google/callback")
def google_callback(session, request, code: str = "", state: str = "", error: str = ""):
    if error or not code or state != session.pop("google_oauth_state", None):
        return RedirectResponse("/login?error=Google+sign-in+failed", status_code=303)
    identity = google_auth.exchange(request, code)
    if not identity:
        return RedirectResponse("/login?error=Google+account+is+not+authorised", status_code=303)
    session["user"] = identity["email"]
    return RedirectResponse("/", status_code=303)


@rt("/logout")
def get(session):
    session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


# --- pages ------------------------------------------------------------------

@rt("/")
def get(session):
    if not _user(session):
        return landing_page()
    return _guard(session, "dashboard", views.dashboard)


@rt("/deals")
def get(session):
    return _guard(session, "deals", views.deals_kanban)


@rt("/deals/new")
def get(session):
    return _guard(session, "deals", views.new_deal_form)


@rt("/deals/new")
def post(session, org_id: int = 0, deal_value: float = 0, stage: str = "Qualification", next_step: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    did = db.create_deal(org_id, deal_value, stage, next_step)
    return RedirectResponse(f"/deals/{did}", status_code=303)


@rt("/deals/{deal_id}")
def get(session, deal_id: int):
    return _guard(session, "deals", lambda: views.deal_detail(deal_id))


def _frag(session, deal_id):
    """Return the deal-main fragment (HTMX) if authed."""
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    return views.deal_main(deal_id)


@rt("/deals/{deal_id}/stage")
def post(session, deal_id: int, stage: str = ""):
    db.set_deal_stage(deal_id, stage)
    return _frag(session, deal_id)


@rt("/deals/{deal_id}/edit")
def post(session, deal_id: int, deal_value: float = None, next_step: str = ""):
    db.update_deal(deal_id, deal_value=deal_value, next_step=next_step)
    return _frag(session, deal_id)


@rt("/deals/{deal_id}/note")
def post(session, deal_id: int, body: str = ""):
    if body.strip():
        db.log_activity("deal", deal_id, "note", body.strip())
    return _frag(session, deal_id)


@rt("/deals/{deal_id}/task")
def post(session, deal_id: int, title: str = "", priority: str = "Medium"):
    if title.strip():
        db.add_task("deal", deal_id, title.strip(), priority)
    return _frag(session, deal_id)


@rt("/deals/{deal_id}/email")
def post(session, deal_id: int, to: str = "", subject: str = "", body: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.log_email("deal", deal_id, to, subject, body)
    return _frag(session, deal_id)


@rt("/tasks/{task_id}/status")
def post(session, task_id: int, status: str = ""):
    t = db.one("SELECT ref_type, ref_id FROM tasks WHERE id=?", (task_id,))
    db.set_task_status(task_id, status)
    if t and t["ref_type"] == "deal":
        return _frag(session, t["ref_id"])
    return Response("ok")


@rt("/leads")
def get(session, status: str = "All", q: str = "", source: str = "All",
        owner_id: str = "All", sort: str = "newest", view: int = 0):
    return _guard(session, "leads",
                  lambda: views.leads_list(status, q, source, owner_id, sort, view))


@rt("/leads/new")
def get(session):
    return _guard(session, "leads", views.new_lead_form)


@rt("/leads/new")
def post(session, first_name: str = "", last_name: str = "", organization: str = "",
         email: str = "", source: str = "Website", est_value: float = 0):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    if not first_name.strip():
        return RedirectResponse("/leads/new", status_code=303)
    lid = db.create_lead(first_name.strip(), last_name.strip(), organization.strip(),
                         email.strip(), source, est_value=est_value)
    return RedirectResponse(f"/leads/{lid}", status_code=303)


# --- saved views (defined before /leads/{lead_id} so they aren't shadowed) ---

@rt("/leads/views/save")
def post(session, name: str = "", status: str = "All", source: str = "All",
         owner_id: str = "All", q: str = "", sort: str = "newest"):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    vid = db.create_saved_view(name, "leads", {
        "status": status, "source": source, "owner_id": owner_id, "q": q, "sort": sort})
    return RedirectResponse(f"/leads?view={vid}" if vid else "/leads", status_code=303)


@rt("/leads/views/{vid}/delete")
def post(session, vid: int):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.delete_saved_view(vid)
    # return the refreshed chip bar (outerHTML swap on #sv-bar)
    return views._saved_view_chips("leads") or Div(id="sv-bar")


@rt("/leads/{lead_id}/email")
def post(session, lead_id: int, to: str = "", subject: str = "", body: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.log_email("lead", lead_id, to, subject, body)
    return Response(headers={"HX-Redirect": f"/leads/{lead_id}"})


@rt("/leads/{lead_id}")
def get(session, lead_id: int):
    return _guard(session, "leads", lambda: views.lead_detail(lead_id))


@rt("/tasks")
def get(session, status: str = "Open"):
    return _guard(session, "tasks", lambda: views.tasks_list(status))


@rt("/contacts")
def get(session, q: str = ""):
    return _guard(session, "contacts", lambda: views.contacts_list(q))


@rt("/organizations")
def get(session):
    return _guard(session, "organizations", views.orgs_list)


@rt("/ai")
def get(session):
    body = (views._title("AI Assistant", "Chat lives in the right rail. Ask in plain English or use slash-commands."),
            Div(NotStr(
                "<div class='card'><h3>What you can ask</h3>"
                "<ul style='line-height:1.8;'>"
                "<li>“What's the state of my pipeline?”</li>"
                "<li>“Which deals are closest to closing?”</li>"
                "<li>“Summarise our leads by status.”</li>"
                "<li>“Tell me about Northwind Labs.”</li></ul>"
                "<p style='color:var(--text-mute)'>Slash-commands resolve instantly without an API key: "
                "<code>/pipeline</code> <code>/deals</code> <code>/leads</code> <code>/tasks</code> "
                "<code>/kpi</code> <code>/org &lt;name&gt;</code> <code>/help</code></p></div>")))
    return _guard(session, "ai", body)


@rt("/guide")
def get(session):
    return _guard(session, "guide", _guide_body)


def _guide_body():
    return views._title("User Guide", "How to drive FastCRM"), Div(NotStr("""
<div class='card'><h3>Dashboard</h3><p>Headline KPIs, your pipeline funnel by stage,
the top open deals, and a live activity feed.</p></div>
<div class='card'><h3>Deals (Kanban)</h3><p>Every deal sits in a pipeline column from
<em>Qualification</em> to <em>Won</em>/<em>Lost</em>. Click a card to open the deal, with its
contact, tasks and full activity timeline.</p></div>
<div class='card'><h3>Leads</h3><p>Filter by status (New → Qualified → Junk), search by name
or company, and drill into any lead's activity.</p></div>
<div class='card'><h3>Tasks, Contacts, Organizations</h3><p>Track open work, browse people and the
companies they belong to, ranked by won value.</p></div>
<div class='card'><h3>AI Assistant</h3><p>The right rail chats over a live snapshot of your CRM.
Use plain English or slash-commands. Set <code>MODEL_PROVIDER</code> + an API key in
<code>.env</code> for free-form chat; slash-commands always work.</p></div>
"""))


# --- chat -------------------------------------------------------------------

@rt("/chat/new")
def get(session):
    session["thread"] = uuid.uuid4().hex
    return P("Ask about your pipeline, leads, deals or tasks — or tap a question below.",
             cls="chat-empty-hint")


@rt("/chat/stream")
async def post(session, message: str = "", thread_id: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    message = (message or "").strip()
    if not message:
        return Response("No message", status_code=400)

    tid = thread_id or _thread(session)

    async def gen():
        with db.cursor() as conn:
            conn.execute(
                "INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                (tid, "user", message))
        full = []
        async for chunk in ai.stream_chat(message):
            # tee assistant tokens for persistence
            if chunk.startswith("data: "):
                try:
                    import json as _j
                    tok = _j.loads(chunk[6:]).get("token")
                    if tok:
                        full.append(tok)
                except Exception:
                    pass
            yield chunk
        with db.cursor() as conn:
            conn.execute(
                "INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                (tid, "assistant", "".join(full)))

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- boot -------------------------------------------------------------------

def _ensure_db():
    if not db.db_exists():
        logger.info("No database found — seeding synthetic data…")
        import seed
        seed.build()


_ensure_db()

if __name__ == "__main__":
    logger.info("FastCRM on http://localhost:%s  (login %s)", PORT, VALID_EMAIL)
    serve(port=PORT, reload=os.getenv("FASTCRM_RELOAD", "0") == "1")
