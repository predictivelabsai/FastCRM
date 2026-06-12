"""Generate a fully synthetic FastCRM database.

Deterministic (fixed RNG seed) so every run produces the same demo data — no
real people, companies, or PII anywhere. Run:

    python seed.py            # builds ./fastcrm.sqlite (or $FASTCRM_DB)

Re-running drops and rebuilds the tables.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import db

RNG = random.Random(20260611)
NOW = datetime(2026, 6, 11, 9, 0, 0)


def _dt(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago, hours=RNG.randint(0, 9))).strftime("%Y-%m-%d %H:%M:%S")


def _date(days_from_now: float) -> str:
    return (NOW + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


FIRST_NAMES = [
    "Aisha", "Liam", "Sofia", "Noah", "Mia", "Ethan", "Priya", "Lucas",
    "Chloe", "Mateo", "Hana", "Omar", "Isla", "Diego", "Yuki", "Nora",
    "Kai", "Zara", "Leo", "Amara", "Felix", "Ravi", "Elena", "Tariq",
    "Maya", "Sven", "Ingrid", "Marco", "Lena", "Pablo",
]
LAST_NAMES = [
    "Okafor", "Nguyen", "Rossi", "Andersen", "Kim", "Haddad", "Silva",
    "Müller", "Costa", "Tanaka", "Khan", "Lindqvist", "Moreau", "Ito",
    "Petrov", "Schmidt", "Dubois", "Reyes", "Novak", "Bauer", "Mensah",
    "Sato", "Larsen", "Romano", "Singh", "Fischer", "Mwangi", "Park",
]
ORG_PREFIX = [
    "Northwind", "Apex", "Lumen", "Helios", "Vertex", "Cobalt", "Acme",
    "Bluewave", "Sterling", "Quanta", "Evergreen", "Meridian", "Ironclad",
    "Solstice", "Pinnacle", "Nimbus", "Atlas", "Beacon", "Cascade", "Forge",
    "Granite", "Harbor", "Juniper", "Keystone", "Lattice", "Monarch",
    "Orbit", "Polaris", "Summit", "Tideline",
]
ORG_SUFFIX = ["Labs", "Systems", "Group", "Industries", "Logistics", "Health",
              "Digital", "Partners", "Works", "Foods", "Energy", "Retail"]
JOB_TITLES = [
    "Procurement Lead", "Head of Operations", "CTO", "Founder", "VP Sales",
    "Office Manager", "IT Director", "Finance Manager", "COO", "Plant Manager",
    "Marketing Director", "Owner",
]
TERRITORIES = ["UK", "DACH", "Nordics", "Iberia", "Benelux", "North America", "APAC"]
NEXT_STEPS = [
    "Send proposal", "Schedule demo", "Follow up on pricing", "Awaiting sign-off",
    "Book technical call", "Send contract", "Chase decision maker", "Check budget",
]
NOTE_BODIES = [
    "Spoke with the team — strong interest in the analytics module.",
    "Budget approved for Q3; they want onboarding support.",
    "Competitor is also in the running; price is the key lever.",
    "Decision maker is on leave until next week.",
    "Asked for a security questionnaire — sent to legal.",
    "Great demo, very positive. Pushing for a pilot.",
    "Needs sign-off from finance before proceeding.",
    "Reduced scope to fit budget; revised quote sent.",
]


def _money(low, high):
    return float(RNG.randint(low, high) * 100)


def build():
    db.init_schema()
    with db.cursor() as conn:
        for t in ("activities", "call_logs", "tasks", "notes", "deals",
                  "leads", "contacts", "organizations", "users", "chat_messages",
                  "saved_views"):
            conn.execute(f"DELETE FROM {t}")

    # --- users (sales reps) -------------------------------------------------
    reps = []
    used = set()
    for _ in range(6):
        fn, ln = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
        email = f"{fn.lower()}.{ln.lower()}@fastcrm.example"
        if email in used:
            continue
        used.add(email)
        reps.append((f"{fn} {ln}", email))
    with db.cursor() as conn:
        conn.executemany("INSERT INTO users(name,email) VALUES (?,?)", reps)
        rep_ids = [r[0] for r in conn.execute("SELECT id FROM users").fetchall()]

    # --- organizations ------------------------------------------------------
    orgs = []
    seen = set()
    for _ in range(28):
        name = f"{RNG.choice(ORG_PREFIX)} {RNG.choice(ORG_SUFFIX)}"
        if name in seen:
            continue
        seen.add(name)
        slug = name.lower().replace(" ", "")
        orgs.append((
            name, f"https://{slug}.example", RNG.choice(db.INDUSTRIES),
            RNG.choice(db.EMPLOYEE_BANDS), _money(5000, 900000),
            RNG.choice(TERRITORIES), _dt(RNG.randint(120, 800)),
        ))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO organizations
               (name,website,industry,employee_band,annual_revenue,territory,created)
               VALUES (?,?,?,?,?,?,?)""", orgs)
        org_rows = conn.execute("SELECT id,name,industry,territory FROM organizations").fetchall()
    org_ids = [r["id"] for r in org_rows]

    # --- contacts (1-3 per org) --------------------------------------------
    contacts = []
    for o in org_rows:
        for _ in range(RNG.randint(1, 3)):
            fn, ln = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
            contacts.append((
                fn, ln, f"{fn.lower()}.{ln.lower()}@{o['name'].lower().replace(' ', '')}.example",
                f"+44 7{RNG.randint(100, 999)} {RNG.randint(100000, 999999)}",
                RNG.choice(JOB_TITLES), o["id"], _dt(RNG.randint(30, 700)),
            ))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO contacts
               (first_name,last_name,email,mobile,job_title,org_id,created)
               VALUES (?,?,?,?,?,?,?)""", contacts)
        contact_rows = conn.execute("SELECT id,org_id FROM contacts").fetchall()
    contacts_by_org: dict[int, list[int]] = {}
    for c in contact_rows:
        contacts_by_org.setdefault(c["org_id"], []).append(c["id"])

    # --- leads --------------------------------------------------------------
    # Weight towards the top of the funnel.
    status_weights = [("New", 30), ("Contacted", 24), ("Nurture", 18),
                      ("Qualified", 14), ("Unqualified", 8), ("Junk", 6)]
    statuses = [s for s, w in status_weights for _ in range(w)]
    leads = []
    for _ in range(80):
        fn, ln = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
        st = RNG.choice(statuses)
        org_name = f"{RNG.choice(ORG_PREFIX)} {RNG.choice(ORG_SUFFIX)}"
        created_days = RNG.randint(1, 180)
        leads.append((
            fn, ln, org_name, RNG.choice(JOB_TITLES),
            f"{fn.lower()}.{ln.lower()}@{org_name.lower().replace(' ', '')}.example",
            f"+44 7{RNG.randint(100, 999)} {RNG.randint(100000, 999999)}",
            st, RNG.choice(db.LEAD_SOURCES), RNG.choice(db.INDUSTRIES),
            RNG.choice(db.EMPLOYEE_BANDS), _money(2000, 600000),
            RNG.choice(TERRITORIES), RNG.choice(rep_ids),
            1 if st == "Qualified" and RNG.random() < 0.4 else 0,
            _dt(created_days), _dt(max(0, created_days - RNG.randint(0, created_days))),
        ))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO leads
               (first_name,last_name,organization,job_title,email,mobile,status,
                source,industry,employee_band,annual_revenue,territory,owner_id,
                converted,created,last_activity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", leads)
        lead_ids = [r[0] for r in conn.execute("SELECT id FROM leads").fetchall()]

    # --- deals --------------------------------------------------------------
    stage_weights = [("Qualification", 16), ("Demo/Making", 12),
                     ("Proposal/Quotation", 11), ("Negotiation", 9),
                     ("Ready to Close", 6), ("Won", 18), ("Lost", 10)]
    stages = [s for s, w in stage_weights for _ in range(w)]
    prob_for = {"Qualification": 20, "Demo/Making": 35, "Proposal/Quotation": 55,
                "Negotiation": 70, "Ready to Close": 90, "Won": 100, "Lost": 0}
    deals = []
    for _ in range(60):
        oid = RNG.choice(org_ids)
        cid = RNG.choice(contacts_by_org.get(oid, [None]))
        stage = RNG.choice(stages)
        created_days = RNG.randint(2, 150)
        closed = None
        if stage in ("Won", "Lost"):
            closed = _date(-RNG.randint(0, created_days // 2 + 1))
        deals.append((
            oid, cid, RNG.choice(lead_ids), RNG.choice(rep_ids), stage,
            _money(20, 4000), prob_for[stage], RNG.choice(db.LEAD_SOURCES),
            RNG.choice(db.INDUSTRIES), RNG.choice(NEXT_STEPS),
            _date(RNG.randint(-10, 90)), closed,
            _dt(created_days), _dt(RNG.randint(0, created_days)),
        ))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO deals
               (org_id,contact_id,lead_id,owner_id,stage,deal_value,probability,
                source,industry,next_step,expected_close,closed_date,created,last_activity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", deals)
        deal_rows = conn.execute("SELECT id,stage FROM deals").fetchall()

    # --- tasks --------------------------------------------------------------
    task_titles = [
        "Call to confirm requirements", "Prepare proposal", "Send pricing sheet",
        "Schedule product demo", "Follow up after demo", "Draft contract",
        "Check in on decision", "Share case study", "Book onboarding call",
        "Renewal conversation",
    ]
    tasks = []
    for _ in range(70):
        ref = RNG.choice(deal_rows)
        st = RNG.choices(db.TASK_STATUSES, weights=[10, 30, 20, 30, 10])[0]
        tasks.append((
            RNG.choice(task_titles), RNG.choice(db.TASK_PRIORITIES), st,
            _date(RNG.randint(-7, 21)), RNG.choice(rep_ids),
            "deal", ref["id"],
            "Auto-generated demo task.", _dt(RNG.randint(0, 40)),
        ))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO tasks
               (title,priority,status,due_date,assignee_id,ref_type,ref_id,description,created)
               VALUES (?,?,?,?,?,?,?,?,?)""", tasks)

    # --- notes + activities + call logs ------------------------------------
    acts, notes, calls = [], [], []
    for d in deal_rows:
        n = RNG.randint(2, 6)
        for _ in range(n):
            kind = RNG.choices(db.ACTIVITY_TYPES, weights=[35, 20, 20, 15, 10])[0]
            body = RNG.choice(NOTE_BODIES) if kind in ("note", "email") else {
                "call": "Logged a call with the contact.",
                "status": "Stage advanced.",
                "task": "Task created from the activity feed.",
            }.get(kind, "")
            created = _dt(RNG.randint(0, 60))
            acts.append(("deal", d["id"], kind, body, RNG.choice(rep_ids), created))
            if kind == "note":
                notes.append((RNG.choice(["Call summary", "Internal note", "Next steps"]),
                              body, "deal", d["id"], RNG.choice(rep_ids), created))
            if kind == "call":
                calls.append((
                    RNG.choice(["Incoming", "Outgoing"]),
                    RNG.choice(["Completed", "Completed", "No Answer", "Busy"]),
                    RNG.randint(30, 900), "deal", d["id"], RNG.choice(rep_ids), created,
                ))
    for lid in RNG.sample(lead_ids, 40):
        for _ in range(RNG.randint(1, 3)):
            acts.append(("lead", lid, RNG.choice(["note", "call", "email"]),
                         RNG.choice(NOTE_BODIES), RNG.choice(rep_ids),
                         _dt(RNG.randint(0, 60))))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO activities (ref_type,ref_id,kind,body,owner_id,created)
               VALUES (?,?,?,?,?,?)""", acts)
        conn.executemany(
            """INSERT INTO notes (title,content,ref_type,ref_id,owner_id,created)
               VALUES (?,?,?,?,?,?)""", notes)
        conn.executemany(
            """INSERT INTO call_logs
               (direction,status,duration,ref_type,ref_id,caller_id,start_time)
               VALUES (?,?,?,?,?,?,?)""", calls)

    print(f"FastCRM seeded → {db.DB_PATH}")
    print(f"  {len(reps)} reps · {len(orgs)} orgs · {len(contacts)} contacts · "
          f"{len(leads)} leads · {len(deals)} deals · {len(tasks)} tasks · "
          f"{len(acts)} activities")


if __name__ == "__main__":
    build()
