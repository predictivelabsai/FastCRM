"""FastCRM data layer — a thin wrapper over SQLite.

The schema mirrors the core of Frappe CRM (leads, deals, contacts,
organizations, tasks, notes, activities, call logs) collapsed into a compact,
read-friendly relational model. Everything is synthetic; see ``seed.py``.

The database path is resolved from ``FASTCRM_DB`` (env) or defaults to
``fastcrm.sqlite`` beside this file. In Docker, mount a volume and point
``FASTCRM_DB`` at it so the data survives image rebuilds.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("FASTCRM_DB") or str(Path(__file__).parent / "fastcrm.sqlite")

# --- domain vocabularies (kept here so seed + UI agree) ---------------------

LEAD_STATUSES = ["New", "Contacted", "Nurture", "Qualified", "Unqualified", "Junk"]

# Deal pipeline stages, in order. "Won"/"Lost" are terminal.
DEAL_STAGES = [
    "Qualification",
    "Demo/Making",
    "Proposal/Quotation",
    "Negotiation",
    "Ready to Close",
    "Won",
    "Lost",
]
OPEN_STAGES = DEAL_STAGES[:5]

TASK_STATUSES = ["Backlog", "Todo", "In Progress", "Done", "Canceled"]
TASK_PRIORITIES = ["Low", "Medium", "High"]

LEAD_SOURCES = [
    "Website", "Cold Call", "Referral", "Advertisement",
    "Event/Webinar", "Existing Customer", "Partner", "Social Media",
]
INDUSTRIES = [
    "Technology", "Manufacturing", "Healthcare", "Financial Services",
    "Retail", "Education", "Construction", "Logistics", "Energy", "Media",
]
EMPLOYEE_BANDS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"]
ACTIVITY_TYPES = ["note", "call", "email", "status", "task"]


# --- connection -------------------------------------------------------------

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    p = Path(DB_PATH)
    return p.exists() and p.stat().st_size > 0


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql: str, params: tuple = ()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


# --- schema -----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS organizations (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    website         TEXT,
    industry        TEXT,
    employee_band   TEXT,
    annual_revenue  REAL,
    territory       TEXT,
    created         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY,
    first_name    TEXT,
    last_name     TEXT,
    email         TEXT,
    mobile        TEXT,
    job_title     TEXT,
    org_id        INTEGER REFERENCES organizations(id),
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    organization    TEXT,
    job_title       TEXT,
    email           TEXT,
    mobile          TEXT,
    status          TEXT NOT NULL,
    source          TEXT,
    industry        TEXT,
    employee_band   TEXT,
    annual_revenue  REAL,
    territory       TEXT,
    owner_id        INTEGER REFERENCES users(id),
    converted       INTEGER NOT NULL DEFAULT 0,
    created         TEXT NOT NULL,
    last_activity   TEXT
);

CREATE TABLE IF NOT EXISTS deals (
    id                 INTEGER PRIMARY KEY,
    org_id             INTEGER REFERENCES organizations(id),
    contact_id         INTEGER REFERENCES contacts(id),
    lead_id            INTEGER REFERENCES leads(id),
    owner_id           INTEGER REFERENCES users(id),
    stage              TEXT NOT NULL,
    deal_value         REAL NOT NULL DEFAULT 0,
    probability        INTEGER NOT NULL DEFAULT 0,
    source             TEXT,
    industry           TEXT,
    next_step          TEXT,
    expected_close     TEXT,
    closed_date        TEXT,
    created            TEXT NOT NULL,
    last_activity      TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    priority      TEXT NOT NULL,
    status        TEXT NOT NULL,
    due_date      TEXT,
    assignee_id   INTEGER REFERENCES users(id),
    ref_type      TEXT,            -- 'lead' | 'deal' | NULL
    ref_id        INTEGER,
    description   TEXT,
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id            INTEGER PRIMARY KEY,
    title         TEXT,
    content       TEXT,
    ref_type      TEXT,
    ref_id        INTEGER,
    owner_id      INTEGER REFERENCES users(id),
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id            INTEGER PRIMARY KEY,
    ref_type      TEXT NOT NULL,   -- 'lead' | 'deal'
    ref_id        INTEGER NOT NULL,
    kind          TEXT NOT NULL,   -- note | call | email | status | task
    body          TEXT,
    owner_id      INTEGER REFERENCES users(id),
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_logs (
    id            INTEGER PRIMARY KEY,
    direction     TEXT NOT NULL,   -- Incoming | Outgoing
    status        TEXT NOT NULL,
    duration      INTEGER,         -- seconds
    ref_type      TEXT,
    ref_id        INTEGER,
    caller_id     INTEGER REFERENCES users(id),
    start_time    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id            INTEGER PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_views (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    entity        TEXT NOT NULL,   -- 'leads' | 'deals'
    filters       TEXT NOT NULL,   -- JSON: {status, source, owner_id, q, sort}
    created       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deals_stage   ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_leads_status  ON leads(status);
CREATE INDEX IF NOT EXISTS idx_act_ref       ON activities(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_tasks_ref     ON tasks(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_chat_thread   ON chat_messages(thread_id);
"""


def init_schema() -> None:
    with cursor() as conn:
        conn.executescript(SCHEMA)


# --- read helpers used across views + AI tools ------------------------------

def kpis() -> dict:
    """Headline cockpit numbers."""
    open_q = ",".join("?" * len(OPEN_STAGES))
    won_value = scalar("SELECT COALESCE(SUM(deal_value),0) FROM deals WHERE stage='Won'") or 0
    open_value = scalar(
        f"SELECT COALESCE(SUM(deal_value),0) FROM deals WHERE stage IN ({open_q})",
        tuple(OPEN_STAGES),
    ) or 0
    won = scalar("SELECT COUNT(*) FROM deals WHERE stage='Won'") or 0
    lost = scalar("SELECT COUNT(*) FROM deals WHERE stage='Lost'") or 0
    return {
        "open_deals": scalar(
            f"SELECT COUNT(*) FROM deals WHERE stage IN ({open_q})", tuple(OPEN_STAGES)
        ) or 0,
        "open_value": open_value,
        "won_value": won_value,
        "new_leads": scalar("SELECT COUNT(*) FROM leads WHERE status='New'") or 0,
        "total_leads": scalar("SELECT COUNT(*) FROM leads") or 0,
        "open_tasks": scalar(
            "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('Done','Canceled')"
        ) or 0,
        "win_rate": round(100 * won / (won + lost)) if (won + lost) else 0,
    }


def pipeline_by_stage() -> list[dict]:
    out = []
    for stage in DEAL_STAGES:
        r = one(
            "SELECT COUNT(*) n, COALESCE(SUM(deal_value),0) v FROM deals WHERE stage=?",
            (stage,),
        )
        out.append({"stage": stage, "count": r["n"], "value": r["v"]})
    return out


def deals_in_stage(stage: str) -> list[dict]:
    return rows(
        """SELECT d.*, o.name AS org_name, u.name AS owner_name,
                  c.first_name AS c_first, c.last_name AS c_last
           FROM deals d
           LEFT JOIN organizations o ON o.id = d.org_id
           LEFT JOIN users u ON u.id = d.owner_id
           LEFT JOIN contacts c ON c.id = d.contact_id
           WHERE d.stage = ?
           ORDER BY d.deal_value DESC""",
        (stage,),
    )


def lead(lead_id: int) -> dict | None:
    return one(
        """SELECT l.*, u.name AS owner_name
           FROM leads l LEFT JOIN users u ON u.id = l.owner_id
           WHERE l.id = ?""",
        (lead_id,),
    )


def deal(deal_id: int) -> dict | None:
    return one(
        """SELECT d.*, o.name AS org_name, o.website AS org_website,
                  u.name AS owner_name,
                  c.first_name AS c_first, c.last_name AS c_last,
                  c.email AS c_email, c.mobile AS c_mobile, c.job_title AS c_title
           FROM deals d
           LEFT JOIN organizations o ON o.id = d.org_id
           LEFT JOIN users u ON u.id = d.owner_id
           LEFT JOIN contacts c ON c.id = d.contact_id
           WHERE d.id = ?""",
        (deal_id,),
    )


def activities_for(ref_type: str, ref_id: int) -> list[dict]:
    return rows(
        """SELECT a.*, u.name AS owner_name
           FROM activities a LEFT JOIN users u ON u.id = a.owner_id
           WHERE a.ref_type = ? AND a.ref_id = ?
           ORDER BY a.created DESC""",
        (ref_type, ref_id),
    )


def tasks_for(ref_type: str, ref_id: int) -> list[dict]:
    return rows(
        """SELECT t.*, u.name AS assignee_name
           FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id
           WHERE t.ref_type = ? AND t.ref_id = ?
           ORDER BY (t.status IN ('Done','Canceled')), t.due_date""",
        (ref_type, ref_id),
    )


# --- write operations (transactional) ---------------------------------------

def log_activity(ref_type: str, ref_id: int, kind: str, body: str, owner_id=None):
    with cursor() as conn:
        if owner_id is None:
            r = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
            owner_id = r[0] if r else None
        conn.execute(
            "INSERT INTO activities(ref_type,ref_id,kind,body,owner_id,created) "
            "VALUES (?,?,?,?,?,datetime('now'))",
            (ref_type, ref_id, kind, body, owner_id))


def set_deal_stage(deal_id: int, stage: str) -> bool:
    if stage not in DEAL_STAGES:
        return False
    cur = deal(deal_id)
    if not cur or cur["stage"] == stage:
        return False
    prob = {"Qualification": 20, "Demo/Making": 35, "Proposal/Quotation": 55,
            "Negotiation": 70, "Ready to Close": 90, "Won": 100, "Lost": 0}.get(stage, cur["probability"])
    closed = "date('now')" if stage in ("Won", "Lost") else "NULL"
    with cursor() as conn:
        conn.execute(
            f"UPDATE deals SET stage=?, probability=?, last_activity=datetime('now'), "
            f"closed_date={closed} WHERE id=?", (stage, prob, deal_id))
    log_activity("deal", deal_id, "status", f"Stage moved from <strong>{cur['stage']}</strong> to <strong>{stage}</strong>.")
    return True


def update_deal(deal_id: int, deal_value=None, next_step=None, expected_close=None):
    sets, params = [], []
    if deal_value is not None:
        sets.append("deal_value=?"); params.append(deal_value)
    if next_step is not None:
        sets.append("next_step=?"); params.append(next_step)
    if expected_close is not None:
        sets.append("expected_close=?"); params.append(expected_close)
    if not sets:
        return
    sets.append("last_activity=datetime('now')")
    params.append(deal_id)
    with cursor() as conn:
        conn.execute(f"UPDATE deals SET {', '.join(sets)} WHERE id=?", tuple(params))


def add_task(ref_type: str, ref_id: int, title: str, priority="Medium", due_date=None):
    with cursor() as conn:
        owner = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        conn.execute(
            "INSERT INTO tasks(title,priority,status,due_date,assignee_id,ref_type,ref_id,description,created) "
            "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
            (title, priority if priority in TASK_PRIORITIES else "Medium", "Todo",
             due_date, owner[0] if owner else None, ref_type, ref_id, ""))
    log_activity(ref_type, ref_id, "task", f"Task added: <strong>{title}</strong>.")


def set_task_status(task_id: int, status: str):
    if status not in TASK_STATUSES:
        return
    with cursor() as conn:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))


def create_lead(first_name, last_name, organization, email, source, status="New", est_value=0):
    with cursor() as conn:
        owner = conn.execute("SELECT id FROM users ORDER BY RANDOM() LIMIT 1").fetchone()
        conn.execute(
            """INSERT INTO leads(first_name,last_name,organization,email,status,source,
               annual_revenue,owner_id,converted,created,last_activity)
               VALUES (?,?,?,?,?,?,?,?,0,datetime('now'),datetime('now'))""",
            (first_name, last_name, organization, email,
             status if status in LEAD_STATUSES else "New",
             source if source in LEAD_SOURCES else "Website",
             est_value or 0, owner[0] if owner else None))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def create_deal(org_id, deal_value, stage="Qualification", next_step="", contact_id=None):
    prob = {"Qualification": 20, "Demo/Making": 35, "Proposal/Quotation": 55,
            "Negotiation": 70, "Ready to Close": 90, "Won": 100, "Lost": 0}.get(stage, 20)
    with cursor() as conn:
        owner = conn.execute("SELECT id FROM users ORDER BY RANDOM() LIMIT 1").fetchone()
        if contact_id is None:
            c = conn.execute("SELECT id FROM contacts WHERE org_id=? LIMIT 1", (org_id,)).fetchone()
            contact_id = c[0] if c else None
        conn.execute(
            """INSERT INTO deals(org_id,contact_id,owner_id,stage,deal_value,probability,
               source,next_step,expected_close,created,last_activity)
               VALUES (?,?,?,?,?,?,?,?,date('now','+30 day'),datetime('now'),datetime('now'))""",
            (org_id, contact_id, owner[0] if owner else None,
             stage if stage in DEAL_STAGES else "Qualification",
             deal_value or 0, prob, "Website", next_step))
        did = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_activity("deal", did, "note", "Deal created.")
    return did


def organizations() -> list[dict]:
    return rows("SELECT id, name FROM organizations ORDER BY name")


def users() -> list[dict]:
    return rows("SELECT id, name, email FROM users ORDER BY name")


# --- email composer (logs to the activity timeline) -------------------------

def log_email(ref_type: str, ref_id: int, to: str, subject: str, body: str) -> bool:
    to = (to or "").strip()
    subject = (subject or "").strip() or "(no subject)"
    if not to:
        return False
    import html as _html
    preview = _html.escape((body or "").strip())
    if len(preview) > 240:
        preview = preview[:240] + "…"
    formatted = (f"📧 Email to <strong>{_html.escape(to)}</strong> — "
                 f"<strong>{_html.escape(subject)}</strong>"
                 + (f"<br><span style='color:var(--text-mute)'>{preview}</span>" if preview else ""))
    log_activity(ref_type, ref_id, "email", formatted)
    return True


# --- saved / custom views ---------------------------------------------------

def list_saved_views(entity: str) -> list[dict]:
    out = rows("SELECT * FROM saved_views WHERE entity=? ORDER BY name", (entity,))
    for v in out:
        try:
            v["filters_dict"] = json.loads(v["filters"])
        except (ValueError, TypeError):
            v["filters_dict"] = {}
    return out


def saved_view(view_id: int) -> dict | None:
    v = one("SELECT * FROM saved_views WHERE id=?", (view_id,))
    if v:
        try:
            v["filters_dict"] = json.loads(v["filters"])
        except (ValueError, TypeError):
            v["filters_dict"] = {}
    return v


def create_saved_view(name: str, entity: str, filters: dict) -> int | None:
    name = (name or "").strip()
    if not name or entity not in ("leads", "deals"):
        return None
    clean = {k: v for k, v in (filters or {}).items() if v not in (None, "", "All")}
    with cursor() as conn:
        conn.execute("INSERT INTO saved_views(name,entity,filters,created) VALUES (?,?,?,datetime('now'))",
                     (name, entity, json.dumps(clean)))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_saved_view(view_id: int) -> bool:
    with cursor() as conn:
        conn.execute("DELETE FROM saved_views WHERE id=?", (view_id,))
    return True
