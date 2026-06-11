"""FastCRM data layer — a thin wrapper over SQLite.

The schema mirrors the core of Frappe CRM (leads, deals, contacts,
organizations, tasks, notes, activities, call logs) collapsed into a compact,
read-friendly relational model. Everything is synthetic; see ``seed.py``.

The database path is resolved from ``FASTCRM_DB`` (env) or defaults to
``fastcrm.sqlite`` beside this file. In Docker, mount a volume and point
``FASTCRM_DB`` at it so the data survives image rebuilds.
"""
from __future__ import annotations

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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
