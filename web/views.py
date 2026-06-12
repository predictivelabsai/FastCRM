"""Center-pane page renderers for FastCRM."""
from __future__ import annotations

from fasthtml.common import (
    Div, H1, H2, H3, P, Span, A, Table, Thead, Tbody, Tr, Th, Td,
    Ul, Li, Strong, NotStr, Form, Input, Button, Textarea, Select, Option,
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
        _title("Deals", "Move deals through the pipeline — open a card to advance it.",
               A("＋ New deal", href="/deals/new", cls="btn primary")),
        Div(*cols, cls="kanban"),
    )


def new_deal_form():
    orgs = db.organizations()
    return (_title("New deal", "Create a deal in the pipeline.", A("← Deals", href="/deals", cls="btn")),
            Div(Form(
                Span("Organization", style="font-size:11px;text-transform:uppercase;color:var(--text-mute);font-weight:600;"),
                Select(*[Option(o["name"], value=str(o["id"])) for o in orgs], name="org_id",
                       style="width:100%;padding:9px;border:1px solid var(--border);border-radius:8px;margin:4px 0 10px;"),
                Span("Deal value (£)", style="font-size:11px;text-transform:uppercase;color:var(--text-mute);font-weight:600;"),
                Input(type="number", name="deal_value", value="10000", step="500",
                      style="width:100%;padding:9px;border:1px solid var(--border);border-radius:8px;margin:4px 0 10px;"),
                Span("Stage", style="font-size:11px;text-transform:uppercase;color:var(--text-mute);font-weight:600;"),
                Select(*[Option(s, value=s) for s in db.OPEN_STAGES], name="stage",
                       style="width:100%;padding:9px;border:1px solid var(--border);border-radius:8px;margin:4px 0 10px;"),
                Span("Next step", style="font-size:11px;text-transform:uppercase;color:var(--text-mute);font-weight:600;"),
                Input(name="next_step", placeholder="e.g. Send proposal",
                      style="width:100%;padding:9px;border:1px solid var(--border);border-radius:8px;margin:4px 0 12px;"),
                Div(Button("Create deal", cls="btn primary", type="submit"),
                    A("Cancel", href="/deals", cls="btn"), style="display:flex;gap:8px;"),
                method="post", action="/deals/new"),
                cls="card", style="max-width:480px;"))


def new_lead_form():
    return (_title("New lead", "Add a lead to the funnel.", A("← Leads", href="/leads", cls="btn")),
            Div(Form(
                Div(Input(name="first_name", placeholder="First name", required=True, style="flex:1;"),
                    Input(name="last_name", placeholder="Last name", style="flex:1;"),
                    style="display:flex;gap:8px;margin-bottom:10px;"),
                Input(name="organization", placeholder="Organization",
                      style="width:100%;padding:9px;border:1px solid var(--border);border-radius:8px;margin-bottom:10px;"),
                Input(name="email", type="email", placeholder="Email",
                      style="width:100%;padding:9px;border:1px solid var(--border);border-radius:8px;margin-bottom:10px;"),
                Div(Select(*[Option(s, value=s) for s in db.LEAD_SOURCES], name="source", style="flex:1;padding:9px;border:1px solid var(--border);border-radius:8px;"),
                    Input(type="number", name="est_value", placeholder="Est. value £", style="flex:1;padding:9px;border:1px solid var(--border);border-radius:8px;"),
                    style="display:flex;gap:8px;margin-bottom:12px;"),
                Div(Button("Create lead", cls="btn primary", type="submit"),
                    A("Cancel", href="/leads", cls="btn"), style="display:flex;gap:8px;"),
                method="post", action="/leads/new"),
                cls="card", style="max-width:480px;"))


def _stage_mover(deal_id, current):
    """Buttons to move a deal through the pipeline (HTMX, swaps #deal-main)."""
    btns = []
    for s in db.DEAL_STAGES:
        active = s == current
        btns.append(Button(
            s, cls="btn sm" + (" primary" if active else ""),
            disabled=active,
            **({} if active else {
                "hx-post": f"/deals/{deal_id}/stage", "hx-vals": f'{{"stage": "{s}"}}',
                "hx-target": "#deal-main", "hx-swap": "innerHTML"})))
    return Div(*btns, cls="stage-mover")


def deal_main(deal_id: int):
    """The editable body of a deal — returned standalone for HTMX swaps."""
    d = db.deal(deal_id)
    if not d:
        return Div(P("No such deal."))
    acts = db.activities_for("deal", deal_id)
    tasks = db.tasks_for("deal", deal_id)

    info = Div(
        Div(H3("Deal"), Span(f"{d['probability']}% likely", cls="pill"), cls="card-header"),
        _stage_mover(deal_id, d["stage"]),
        Div(Span("Stage", cls="k"), _pill(d["stage"]),
            Span("Value", cls="k"), Strong(money(d["deal_value"])),
            Span("Owner", cls="k"), Span(d["owner_name"] or "—"),
            Span("Expected close", cls="k"), Span(d["expected_close"] or "—"),
            Span("Next step", cls="k"), Span(d["next_step"] or "—"),
            cls="kv", style="margin-top:12px;"),
        Form(
            Input(type="number", name="deal_value", value=int(d["deal_value"] or 0),
                  step="100", style="width:120px;", title="Deal value"),
            Input(type="text", name="next_step", value=d["next_step"] or "",
                  placeholder="Next step", style="flex:1;"),
            Button("Save", cls="btn sm primary", type="submit"),
            **{"hx-post": f"/deals/{deal_id}/edit", "hx-target": "#deal-main", "hx-swap": "innerHTML"},
            cls="inline-form", style="margin-top:10px;"),
        cls="card")

    contact = Div(
        Div(H3("Primary contact"), cls="card-header"),
        Div(Span("Name", cls="k"), Span(_person(d["c_first"], d["c_last"])),
            Span("Title", cls="k"), Span(d["c_title"] or "—"),
            Span("Email", cls="k"), Span(d["c_email"] or "—"),
            Span("Organization", cls="k"),
            Span(A(d["org_name"], href=d["org_website"], target="_blank") if d["org_website"] else (d["org_name"] or "—")),
            cls="kv"),
        cls="card")

    task_rows = [Tr(Td(t["title"]), Td(_pill(t["priority"])),
                    Td(Select(*[Option(s, value=s, selected=(s == t["status"])) for s in db.TASK_STATUSES],
                              name="status", cls="mini-select",
                              **{"hx-post": f"/tasks/{t['id']}/status", "hx-target": "#deal-main",
                                 "hx-swap": "innerHTML", "hx-trigger": "change"})),
                    Td(t["due_date"] or "—")) for t in tasks]
    task_tbl = Table(Thead(Tr(Th("Task"), Th("Priority"), Th("Status"), Th("Due"))),
                     Tbody(*task_rows or [Tr(Td("No tasks yet.", colspan="4"))]), cls="tbl")
    add_task = Form(Input(name="title", placeholder="New task…", required=True, style="flex:1;"),
                    Select(*[Option(p, value=p) for p in db.TASK_PRIORITIES], name="priority"),
                    Button("Add", cls="btn sm primary", type="submit"),
                    **{"hx-post": f"/deals/{deal_id}/task", "hx-target": "#deal-main", "hx-swap": "innerHTML"},
                    cls="inline-form", style="margin-top:10px;")

    timeline = Ul(*[Li(
        Div(Span(a["kind"], cls="kind"), " ", Span(a["created"][:16], cls="when")),
        Div(NotStr(a["body"] or "")),
        Div(a["owner_name"] or "—", style="color:var(--text-mute);font-size:11.5px;"),
    ) for a in acts] or [Li("No activity yet.")], cls="timeline")
    note_form = Form(Input(name="body", placeholder="Log a note…", required=True, style="flex:1;"),
                     Button("Log", cls="btn sm primary", type="submit"),
                     **{"hx-post": f"/deals/{deal_id}/note", "hx-target": "#deal-main", "hx-swap": "innerHTML"},
                     cls="inline-form", style="margin-bottom:12px;")

    composer = _email_composer("deal", deal_id, default_to=d["c_email"] or "",
                               default_subject=f"Re: {d['org_name']} — {money(d['deal_value'])} opportunity")

    return Div(
        Div(info, Div(Div(H3("Tasks"), cls="card-header"), task_tbl, add_task, cls="card"), composer),
        Div(contact, Div(Div(H3("Activity"), cls="card-header"), note_form, timeline, cls="card")),
        cls="detail-grid")


def _email_composer(ref_type, ref_id, default_to="", default_subject="", target="#deal-main"):
    """A compose-email card that logs an 'email' activity to the timeline."""
    return Div(
        Div(H3("✉ Compose email"), cls="card-header"),
        Form(
            Input(name="to", type="email", value=default_to, placeholder="To (email)", required=True,
                  style="width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;"),
            Input(name="subject", value=default_subject, placeholder="Subject",
                  style="width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;"),
            Textarea(placeholder="Write your message…", name="body", rows="4",
                     style="width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;font-family:inherit;"),
            Div(Button("Send & log", cls="btn sm primary", type="submit"),
                Span("Logged to the activity timeline (demo — no mail is sent).",
                     style="color:var(--text-mute);font-size:11.5px;margin-left:8px;"),
                style="display:flex;align-items:center;"),
            **{"hx-post": f"/{ref_type}s/{ref_id}/email", "hx-target": target, "hx-swap": "innerHTML"}),
        cls="card")


def deal_detail(deal_id: int):
    d = db.deal(deal_id)
    if not d:
        return _title("Deal not found"), P("No such deal.")
    return (
        _title(f"{d['org_name']} — {money(d['deal_value'])}",
               f"Deal #{d['id']}", A("← All deals", href="/deals", cls="btn")),
        Div(deal_main(deal_id), id="deal-main"),
    )


# ---------- leads -----------------------------------------------------------

LEAD_SORTS = {"newest": "l.created DESC", "oldest": "l.created ASC",
              "value": "l.annual_revenue DESC", "name": "l.last_name ASC"}


def _saved_view_chips(entity, active_id=None):
    """Render saved-view chips with a delete (✕) on each."""
    views = db.list_saved_views(entity)
    if not views:
        return None
    chips = []
    for v in views:
        is_active = active_id == v["id"]
        chips.append(Span(
            A(f"★ {v['name']}", href=f"/{entity}?view={v['id']}",
              cls="sv-chip-link" + (" active" if is_active else "")),
            A("✕", href="#", title="Delete view", cls="sv-chip-del",
              **{"hx-post": f"/{entity}/views/{v['id']}/delete", "hx-target": "#sv-bar",
                 "hx-swap": "outerHTML", "hx-confirm": f"Delete saved view “{v['name']}”?"}),
            cls="sv-chip"))
    return Div(Span("Saved views:", cls="sv-label"), *chips, cls="sv-bar", id="sv-bar")


def leads_list(status: str = "All", q: str = "", source: str = "All",
               owner_id: str = "All", sort: str = "newest", view: int = 0):
    # A saved view overrides the individual filter params.
    active_view = None
    if view:
        active_view = db.saved_view(view)
        if active_view:
            f = active_view["filters_dict"]
            status = f.get("status", "All")
            q = f.get("q", "")
            source = f.get("source", "All")
            owner_id = str(f.get("owner_id", "All"))
            sort = f.get("sort", "newest")

    seg = Div(*[A(s, href=f"/leads?status={s}",
                  cls="" + ("active" if status == s else ""))
                for s in ["All"] + db.LEAD_STATUSES], cls="seg")

    where, params = [], []
    if status != "All":
        where.append("l.status=?")
        params.append(status)
    if source != "All":
        where.append("l.source=?")
        params.append(source)
    if owner_id not in ("All", "", None):
        where.append("l.owner_id=?")
        params.append(int(owner_id))
    if q:
        where.append("(l.first_name LIKE ? OR l.last_name LIKE ? OR l.organization LIKE ? OR l.email LIKE ?)")
        params += [f"%{q}%"] * 4
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    order = LEAD_SORTS.get(sort, LEAD_SORTS["newest"])
    leads = db.rows(
        f"""SELECT l.*, u.name owner FROM leads l LEFT JOIN users u ON u.id=l.owner_id
            {clause} ORDER BY {order} LIMIT 200""", tuple(params))

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

    # filter toolbar (GET) — status comes from the segmented control above
    owner_opts = [Option("All owners", value="All", selected=(str(owner_id) == "All"))] + [
        Option(u["name"], value=str(u["id"]), selected=(str(owner_id) == str(u["id"]))) for u in db.users()]
    source_opts = [Option("All sources", value="All", selected=(source == "All"))] + [
        Option(s, value=s, selected=(source == s)) for s in db.LEAD_SOURCES]
    sort_opts = [Option({"newest": "Newest", "oldest": "Oldest", "value": "Value ↓", "name": "Name A–Z"}[k],
                        value=k, selected=(sort == k)) for k in LEAD_SORTS]

    filter_bar = Form(
        Input(type="search", name="q", value=q, placeholder="Search leads…"),
        Select(*source_opts, name="source", cls="filter-select"),
        Select(*owner_opts, name="owner_id", cls="filter-select"),
        Select(*sort_opts, name="sort", cls="filter-select"),
        Input(type="hidden", name="status", value=status),
        Button("Apply", cls="btn sm", type="submit"),
        cls="toolbar", method="get", action="/leads")

    # save-current-view control
    save_form = Form(
        Input(name="name", placeholder="Name this view…", required=True, style="width:170px;"),
        Input(type="hidden", name="status", value=status),
        Input(type="hidden", name="source", value=source),
        Input(type="hidden", name="owner_id", value=str(owner_id)),
        Input(type="hidden", name="q", value=q),
        Input(type="hidden", name="sort", value=sort),
        Button("★ Save view", cls="btn sm primary", type="submit"),
        method="post", action="/leads/views/save",
        cls="inline-form", style="margin-left:auto;")

    sub = f"{len(leads)} shown" + (f" · view: {active_view['name']}" if active_view else "")
    return (_title("Leads", sub, A("＋ New lead", href="/leads/new", cls="btn primary")),
            seg,
            (_saved_view_chips("leads", active_view["id"] if active_view else None) or Div(id="sv-bar")),
            Div(filter_bar, save_form, style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px;"),
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
    composer = _email_composer("lead", lead_id, default_to=l["email"] or "",
                               default_subject=f"Following up — {l['organization'] or 'your enquiry'}",
                               target="this")
    return (
        _title(_person(l["first_name"], l["last_name"]),
               f"Lead #{l['id']}", A("← All leads", href="/leads", cls="btn")),
        Div(info, Div(Div(Div(H3("Activity"), cls="card-header"), timeline, cls="card"), composer),
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
