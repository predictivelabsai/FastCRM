"""Center-pane page renderers for FastCRM."""
from __future__ import annotations

from fasthtml.common import (
    Div, H1, H2, H3, P, Span, A, Table, Thead, Tbody, Tr, Th, Td,
    Ul, Li, Strong, NotStr, Form, Input,
)

import db
from web.layout import kpi_card, money, STAGE_COLORS


def _pill(text: str, kind: str = "") -> Span:
    cls = "pill " + (kind or str(text)).lower().replace(" ", "").replace("/", "")
    return Span(text, cls=cls)


def _title(title: str, sub: str = "", *actions):
    return Div(Div(H1(title), P(sub, cls="sub") if sub else None),
               Div(*actions) if actions else None, cls="page-title")


def _person(first, last) -> str:
    return f"{first or ''} {last or ''}".strip() or "—"


# ---------- dashboard -------------------------------------------------------

def dashboard():
    k = db.kpis()
    pipe = db.pipeline_by_stage()
    max_v = max((p["value"] for p in pipe), default=1) or 1

    funnel = [Div(
        Div(p["stage"], style="color:var(--text-dim);"),
        Div(Div(cls="funnel-bar",
                style=f"width:{max(2, 100*p['value']/max_v):.0f}%;background:{STAGE_COLORS[p['stage']]};")),
        Div(f"{money(p['value'])} · {p['count']}", cls="v"),
        cls="funnel-row") for p in pipe]

    # recent activity feed
    recent = db.rows(
        """SELECT a.kind, a.body, a.created, a.ref_type, a.ref_id, u.name owner,
                  o.name org
           FROM activities a
           LEFT JOIN users u ON u.id=a.owner_id
           LEFT JOIN deals d ON a.ref_type='deal' AND d.id=a.ref_id
           LEFT JOIN organizations o ON o.id=d.org_id
           ORDER BY a.created DESC LIMIT 12""")
    feed = Ul(*[Li(
        Div(Span(r["kind"], cls="kind"), " ",
            Span(r["created"][:16], cls="when")),
        Div(NotStr((r["body"] or "")[:120]), style="margin-top:2px;"),
        Div(f"{r['owner'] or '—'} · {r['org'] or r['ref_type']}",
            style="color:var(--text-mute);font-size:11.5px;margin-top:2px;"),
    ) for r in recent], cls="timeline")

    # top open deals
    top = db.rows(
        f"""SELECT d.id,d.deal_value,d.stage,o.name org,u.name owner
            FROM deals d LEFT JOIN organizations o ON o.id=d.org_id
            LEFT JOIN users u ON u.id=d.owner_id
            WHERE d.stage IN ({','.join('?'*len(db.OPEN_STAGES))})
            ORDER BY d.deal_value DESC LIMIT 8""", tuple(db.OPEN_STAGES))
    top_tbl = Table(
        Thead(Tr(Th("Organization"), Th("Stage"), Th("Owner"), Th("Value"))),
        Tbody(*[Tr(
            Td(A(r["org"], href=f"/deals/{r['id']}")),
            Td(_pill(r["stage"])),
            Td(r["owner"] or "—"),
            Td(money(r["deal_value"]), style="text-align:right;font-weight:600;"),
        ) for r in top]), cls="tbl")

    return (
        _title("Sales Dashboard", "Pipeline health at a glance — fully synthetic demo data."),
        Div(
            kpi_card("Open Deals", k["open_deals"], money(k["open_value"]) + " in play"),
            kpi_card("Won Value", money(k["won_value"]), f"{k['win_rate']}% win rate", won=True),
            kpi_card("New Leads", k["new_leads"], f"{k['total_leads']} total leads"),
            kpi_card("Open Tasks", k["open_tasks"], "across all deals", warn=True),
            cls="kpi-grid"),
        Div(
            Div(Div(H3("Pipeline by stage"), cls="card-header"), *funnel, cls="card"),
            Div(Div(H3("Top open deals"), cls="card-header"), top_tbl, cls="card"),
            cls="grid-2"),
        Div(Div(H3("Recent activity"), cls="card-header"), feed, cls="card"),
    )


# ---------- deals kanban ----------------------------------------------------

def deals_kanban():
    cols = []
    for stage in db.DEAL_STAGES:
        deals = db.deals_in_stage(stage)
        total = sum(d["deal_value"] for d in deals)
        cards = [A(
            Div(d["org_name"] or "—", cls="org"),
            Div(money(d["deal_value"]), cls="val"),
            Div(Span(_person(d["c_first"], d["c_last"])),
                Span(d["owner_name"] or "—"), cls="meta"),
            href=f"/deals/{d['id']}", cls="kan-card",
        ) for d in deals]
        cols.append(Div(
            Div(Div(Span(cls="stage-dot", style=f"background:{STAGE_COLORS[stage]};"), stage),
                Span(f"{len(deals)} · {money(total)}", cls="cnt"), cls="kan-head"),
            Div(*cards, cls="kan-body"), cls="kan-col"))
    return (
        _title("Deals", "Drag-free Kanban across the sales pipeline — click a card to open it."),
        Div(*cols, cls="kanban"),
    )


def deal_detail(deal_id: int):
    d = db.deal(deal_id)
    if not d:
        return _title("Deal not found"), P("No such deal.")
    acts = db.activities_for("deal", deal_id)
    tasks = db.tasks_for("deal", deal_id)

    info = Div(
        Div(H3("Deal"), cls="card-header"),
        Div(
            Span("Stage", cls="k"), _pill(d["stage"]),
            Span("Value", cls="k"), Strong(money(d["deal_value"])),
            Span("Probability", cls="k"), Span(f"{d['probability']}%"),
            Span("Owner", cls="k"), Span(d["owner_name"] or "—"),
            Span("Source", cls="k"), Span(d["source"] or "—"),
            Span("Expected close", cls="k"), Span(d["expected_close"] or "—"),
            Span("Next step", cls="k"), Span(d["next_step"] or "—"),
            cls="kv"),
        cls="card")

    contact = Div(
        Div(H3("Primary contact"), cls="card-header"),
        Div(Span("Name", cls="k"), Span(_person(d["c_first"], d["c_last"])),
            Span("Title", cls="k"), Span(d["c_title"] or "—"),
            Span("Email", cls="k"), Span(d["c_email"] or "—"),
            Span("Mobile", cls="k"), Span(d["c_mobile"] or "—"),
            Span("Organization", cls="k"),
            Span(A(d["org_name"], href=d["org_website"], target="_blank") if d["org_website"] else (d["org_name"] or "—")),
            cls="kv"),
        cls="card")

    task_tbl = Table(
        Thead(Tr(Th("Task"), Th("Priority"), Th("Status"), Th("Due"), Th("Owner"))),
        Tbody(*[Tr(Td(t["title"]), Td(_pill(t["priority"])), Td(_pill(t["status"])),
                   Td(t["due_date"] or "—"), Td(t["assignee_name"] or "—"))
                for t in tasks] or [Tr(Td("No tasks.", colspan="5"))]), cls="tbl")

    timeline = Ul(*[Li(
        Div(Span(a["kind"], cls="kind"), " ", Span(a["created"][:16], cls="when")),
        Div(NotStr(a["body"] or "")),
        Div(a["owner_name"] or "—", style="color:var(--text-mute);font-size:11.5px;"),
    ) for a in acts] or [Li("No activity yet.")], cls="timeline")

    return (
        _title(f"{d['org_name']} — {money(d['deal_value'])}",
               f"Deal #{d['id']} · {d['stage']}", A("← All deals", href="/deals", cls="btn")),
        Div(
            Div(info, Div(Div(H3("Tasks"), cls="card-header"), task_tbl, cls="card")),
            Div(contact,
                Div(Div(H3("Activity"), cls="card-header"), timeline, cls="card")),
            cls="detail-grid"),
    )


# ---------- leads -----------------------------------------------------------

def leads_list(status: str = "All", q: str = ""):
    seg = Div(*[A(s, href=f"/leads?status={s}",
                  cls="" + ("active" if status == s else ""))
                for s in ["All"] + db.LEAD_STATUSES], cls="seg")

    where, params = [], []
    if status != "All":
        where.append("status=?")
        params.append(status)
    if q:
        where.append("(first_name LIKE ? OR last_name LIKE ? OR organization LIKE ? OR email LIKE ?)")
        params += [f"%{q}%"] * 4
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    leads = db.rows(
        f"""SELECT l.*, u.name owner FROM leads l LEFT JOIN users u ON u.id=l.owner_id
            {clause} ORDER BY l.created DESC LIMIT 200""", tuple(params))

    tbl = Table(
        Thead(Tr(Th("Name"), Th("Organization"), Th("Status"), Th("Source"),
                 Th("Owner"), Th("Value"), Th("Created"))),
        Tbody(*[Tr(
            Td(A(_person(l["first_name"], l["last_name"]), href=f"/leads/{l['id']}")),
            Td(l["organization"] or "—"),
            Td(_pill(l["status"])),
            Td(l["source"] or "—"),
            Td(l["owner"] or "—"),
            Td(money(l["annual_revenue"]), style="text-align:right;"),
            Td(l["created"][:10], style="color:var(--text-mute);"),
        ) for l in leads] or [Tr(Td("No leads match.", colspan="7"))]), cls="tbl")

    search = Form(
        Input(type="search", name="q", value=q, placeholder="Search leads…"),
        Input(type="hidden", name="status", value=status),
        cls="toolbar", method="get", action="/leads")

    return (_title("Leads", f"{len(leads)} shown"), seg, search,
            Div(tbl, cls="card"))


def lead_detail(lead_id: int):
    l = db.lead(lead_id)
    if not l:
        return _title("Lead not found"), P("No such lead.")
    acts = db.activities_for("lead", lead_id)
    info = Div(
        Div(H3("Lead"), cls="card-header"),
        Div(Span("Name", cls="k"), Strong(_person(l["first_name"], l["last_name"])),
            Span("Status", cls="k"), _pill(l["status"]),
            Span("Organization", cls="k"), Span(l["organization"] or "—"),
            Span("Job title", cls="k"), Span(l["job_title"] or "—"),
            Span("Email", cls="k"), Span(l["email"] or "—"),
            Span("Mobile", cls="k"), Span(l["mobile"] or "—"),
            Span("Source", cls="k"), Span(l["source"] or "—"),
            Span("Industry", cls="k"), Span(l["industry"] or "—"),
            Span("Owner", cls="k"), Span(l["owner_name"] or "—"),
            Span("Est. value", cls="k"), Span(money(l["annual_revenue"])),
            cls="kv"),
        cls="card")
    timeline = Ul(*[Li(
        Div(Span(a["kind"], cls="kind"), " ", Span(a["created"][:16], cls="when")),
        Div(NotStr(a["body"] or "")),
    ) for a in acts] or [Li("No activity yet.")], cls="timeline")
    return (
        _title(_person(l["first_name"], l["last_name"]),
               f"Lead #{l['id']}", A("← All leads", href="/leads", cls="btn")),
        Div(info, Div(Div(H3("Activity"), cls="card-header"), timeline, cls="card"),
            cls="detail-grid"),
    )


# ---------- tasks -----------------------------------------------------------

def tasks_list(status: str = "Open"):
    seg = Div(*[A(s, href=f"/tasks?status={s}", cls="" + ("active" if status == s else ""))
                for s in ["Open", "All"] + db.TASK_STATUSES], cls="seg")
    if status == "Open":
        clause, params = "WHERE t.status NOT IN ('Done','Canceled')", ()
    elif status == "All":
        clause, params = "", ()
    else:
        clause, params = "WHERE t.status=?", (status,)
    tasks = db.rows(
        f"""SELECT t.*, u.name owner, o.name org, d.id deal_id
            FROM tasks t
            LEFT JOIN users u ON u.id=t.assignee_id
            LEFT JOIN deals d ON t.ref_type='deal' AND d.id=t.ref_id
            LEFT JOIN organizations o ON o.id=d.org_id
            {clause} ORDER BY (t.status IN ('Done','Canceled')), t.due_date LIMIT 200""",
        params)
    tbl = Table(
        Thead(Tr(Th("Task"), Th("Deal"), Th("Priority"), Th("Status"), Th("Due"), Th("Owner"))),
        Tbody(*[Tr(
            Td(t["title"]),
            Td(A(t["org"], href=f"/deals/{t['deal_id']}") if t["deal_id"] else "—"),
            Td(_pill(t["priority"])), Td(_pill(t["status"])),
            Td(t["due_date"] or "—"), Td(t["owner"] or "—"),
        ) for t in tasks] or [Tr(Td("No tasks.", colspan="6"))]), cls="tbl")
    return _title("Tasks", f"{len(tasks)} shown"), seg, Div(tbl, cls="card")


# ---------- contacts & orgs -------------------------------------------------

def contacts_list(q: str = ""):
    clause, params = "", ()
    if q:
        clause = "WHERE c.first_name LIKE ? OR c.last_name LIKE ? OR c.email LIKE ? OR o.name LIKE ?"
        params = tuple([f"%{q}%"] * 4)
    contacts = db.rows(
        f"""SELECT c.*, o.name org, o.website FROM contacts c
            LEFT JOIN organizations o ON o.id=c.org_id {clause}
            ORDER BY c.last_name LIMIT 300""", params)
    tbl = Table(
        Thead(Tr(Th("Name"), Th("Title"), Th("Organization"), Th("Email"), Th("Mobile"))),
        Tbody(*[Tr(
            Td(Strong(_person(c["first_name"], c["last_name"]))),
            Td(c["job_title"] or "—"), Td(c["org"] or "—"),
            Td(c["email"] or "—"), Td(c["mobile"] or "—"),
        ) for c in contacts] or [Tr(Td("No contacts.", colspan="5"))]), cls="tbl")
    search = Form(Input(type="search", name="q", value=q, placeholder="Search contacts…"),
                  cls="toolbar", method="get", action="/contacts")
    return _title("Contacts", f"{len(contacts)} shown"), search, Div(tbl, cls="card")


def orgs_list():
    orgs = db.rows(
        """SELECT o.*, COUNT(DISTINCT c.id) contacts, COUNT(DISTINCT d.id) deals,
                  COALESCE(SUM(CASE WHEN d.stage='Won' THEN d.deal_value END),0) won
           FROM organizations o
           LEFT JOIN contacts c ON c.org_id=o.id
           LEFT JOIN deals d ON d.org_id=o.id
           GROUP BY o.id ORDER BY won DESC, o.name""")
    tbl = Table(
        Thead(Tr(Th("Organization"), Th("Industry"), Th("Size"), Th("Territory"),
                 Th("Contacts"), Th("Deals"), Th("Won"))),
        Tbody(*[Tr(
            Td(A(o["name"], href=o["website"], target="_blank") if o["website"] else o["name"]),
            Td(o["industry"] or "—"), Td(o["employee_band"] or "—"),
            Td(o["territory"] or "—"), Td(str(o["contacts"])), Td(str(o["deals"])),
            Td(money(o["won"]), style="text-align:right;font-weight:600;"),
        ) for o in orgs]), cls="tbl")
    return _title("Organizations", f"{len(orgs)} companies"), Div(tbl, cls="card")
