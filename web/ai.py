"""FastCRM AI assistant.

Two layers:
  1. Slash-commands (``/pipeline``, ``/leads``, ``/deals`` …) resolved locally
     against the database — instant, no API key needed.
  2. Free-form chat streamed from a configurable LLM provider (xAI / OpenAI /
     Anthropic / Google), grounded with a compact, live snapshot of the CRM so
     answers reflect the actual data.

Streaming is plain SSE-style ``data: {json}\\n\\n`` lines consumed by the
vanilla-JS reader in ``layout.py``.
"""
from __future__ import annotations

import json
import os

import db
from web.layout import money

PROVIDER = os.getenv("MODEL_PROVIDER", "xai")
MODEL = os.getenv("MODEL_NAME", "grok-4-1-fast-reasoning")


# ---------- data snapshot (grounding context) -------------------------------

def crm_snapshot() -> str:
    """A compact text snapshot of the CRM, injected into the system prompt."""
    k = db.kpis()
    pipe = db.pipeline_by_stage()
    lines = [
        "CURRENT CRM SNAPSHOT (synthetic demo data):",
        f"- Open deals: {k['open_deals']} worth {money(k['open_value'])}; "
        f"won value {money(k['won_value'])}; win rate {k['win_rate']}%.",
        f"- Leads: {k['total_leads']} total, {k['new_leads']} new. Open tasks: {k['open_tasks']}.",
        "Pipeline by stage (count, value):",
    ]
    for p in pipe:
        lines.append(f"  - {p['stage']}: {p['count']} deals, {money(p['value'])}")
    lead_status = db.rows("SELECT status, COUNT(*) n FROM leads GROUP BY status")
    lines.append("Leads by status: " + ", ".join(f"{r['status']} {r['n']}" for r in lead_status))
    top = db.rows(
        f"""SELECT o.name org, d.deal_value v, d.stage FROM deals d
            LEFT JOIN organizations o ON o.id=d.org_id
            WHERE d.stage IN ({','.join('?'*len(db.OPEN_STAGES))})
            ORDER BY d.deal_value DESC LIMIT 8""", tuple(db.OPEN_STAGES))
    lines.append("Largest open deals: " + "; ".join(f"{r['org']} {money(r['v'])} ({r['stage']})" for r in top))
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the FastCRM assistant, embedded in an open-source sales CRM.
Help the sales team understand their pipeline, leads, deals and tasks.
Be concise and practical. Use Markdown (short tables, bold figures) when it helps.
All data is synthetic demo data — never claim it is real. Base every answer on the
CRM SNAPSHOT below; if something isn't in it, say so plainly rather than inventing."""


# ---------- slash-commands (local, no API) ----------------------------------

def _table(headers, rows_) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows_:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def handle_command(text: str) -> str | None:
    """Return Markdown for a slash-command, or None if not a command."""
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:])

    if cmd in ("help", "?"):
        return ("**FastCRM shortcuts**\n\n"
                "- `/pipeline` — value by stage\n"
                "- `/deals [stage]` — open deals (optionally filter by stage)\n"
                "- `/leads [status]` — lead counts / list\n"
                "- `/tasks` — open tasks\n"
                "- `/kpi` — headline numbers\n"
                "- `/org <name>` — organization summary\n\n"
                "Or just ask a question in plain English.")

    if cmd == "kpi":
        k = db.kpis()
        return _table(["Metric", "Value"], [
            ["Open deals", k["open_deals"]],
            ["Open pipeline", money(k["open_value"])],
            ["Won value", money(k["won_value"])],
            ["Win rate", f"{k['win_rate']}%"],
            ["New leads", k["new_leads"]],
            ["Total leads", k["total_leads"]],
            ["Open tasks", k["open_tasks"]],
        ])

    if cmd == "pipeline":
        pipe = db.pipeline_by_stage()
        return "**Pipeline by stage**\n\n" + _table(
            ["Stage", "Deals", "Value"],
            [[p["stage"], p["count"], money(p["value"])] for p in pipe])

    if cmd == "deals":
        stages = [s for s in db.DEAL_STAGES if s.lower().startswith(arg.lower())] if arg else db.OPEN_STAGES
        rows_ = db.rows(
            f"""SELECT o.name org, d.stage, d.deal_value v, u.name owner
                FROM deals d LEFT JOIN organizations o ON o.id=d.org_id
                LEFT JOIN users u ON u.id=d.owner_id
                WHERE d.stage IN ({','.join('?'*len(stages))})
                ORDER BY d.deal_value DESC LIMIT 15""", tuple(stages))
        if not rows_:
            return "No deals found."
        return "**Deals**\n\n" + _table(["Organization", "Stage", "Value", "Owner"],
                                        [[r["org"], r["stage"], money(r["v"]), r["owner"] or "—"] for r in rows_])

    if cmd == "leads":
        if arg:
            rows_ = db.rows(
                """SELECT first_name||' '||last_name nm, organization org, status, source
                   FROM leads WHERE status LIKE ? ORDER BY created DESC LIMIT 15""", (f"%{arg}%",))
            if not rows_:
                return f"No leads with status like '{arg}'."
            return _table(["Name", "Organization", "Status", "Source"],
                          [[r["nm"], r["org"], r["status"], r["source"]] for r in rows_])
        rows_ = db.rows("SELECT status, COUNT(*) n FROM leads GROUP BY status ORDER BY n DESC")
        return "**Leads by status**\n\n" + _table(["Status", "Count"], [[r["status"], r["n"]] for r in rows_])

    if cmd == "tasks":
        rows_ = db.rows(
            """SELECT t.title, t.priority, t.status, t.due_date, u.name owner
               FROM tasks t LEFT JOIN users u ON u.id=t.assignee_id
               WHERE t.status NOT IN ('Done','Canceled')
               ORDER BY t.due_date LIMIT 15""")
        if not rows_:
            return "No open tasks. 🎉"
        return "**Open tasks**\n\n" + _table(
            ["Task", "Priority", "Status", "Due", "Owner"],
            [[r["title"], r["priority"], r["status"], r["due_date"] or "—", r["owner"] or "—"] for r in rows_])

    if cmd == "org":
        if not arg:
            return "Usage: `/org <name>`"
        o = db.one("SELECT * FROM organizations WHERE name LIKE ? LIMIT 1", (f"%{arg}%",))
        if not o:
            return f"No organization matching '{arg}'."
        deals = db.rows("SELECT stage, deal_value v FROM deals WHERE org_id=?", (o["id"],))
        won = sum(d["v"] for d in deals if d["stage"] == "Won")
        openv = sum(d["v"] for d in deals if d["stage"] in db.OPEN_STAGES)
        return (f"**{o['name']}**\n\n"
                f"- Industry: {o['industry']} · Size: {o['employee_band']} · {o['territory']}\n"
                f"- Deals: {len(deals)} ({money(openv)} open, {money(won)} won)\n"
                f"- Website: {o['website']}")

    return f"Unknown command `/{cmd}`. Try `/help`."


# ---------- streaming chat --------------------------------------------------

async def stream_chat(message: str):
    """Async generator yielding SSE 'data: {...}' lines."""
    # Slash-command? Resolve locally and emit as one chunk.
    cmd = handle_command(message)
    if cmd is not None:
        yield f"data: {json.dumps({'token': cmd})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        return

    system = SYSTEM_PROMPT + "\n\n" + crm_snapshot()
    try:
        async for tok in _provider_stream(system, message):
            yield f"data: {json.dumps({'token': tok})}\n\n"
    except Exception as e:  # noqa: BLE001 — surface to UI
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


async def _provider_stream(system: str, message: str):
    import httpx
    provider = PROVIDER
    model = MODEL

    if provider in ("xai", "openai"):
        url = "https://api.x.ai/v1/chat/completions" if provider == "xai" \
            else "https://api.openai.com/v1/chat/completions"
        key = os.getenv("XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY", "")
        if not key:
            yield _no_key(provider)
            return
        payload = {"model": model, "stream": True,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": message}]}
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, json=payload,
                                     headers={"Authorization": f"Bearer {key}"}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            tok = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                            if tok:
                                yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass

    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            yield _no_key(provider)
            return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream(
                "POST", "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": 1500, "stream": True,
                      "system": system, "messages": [{"role": "user", "content": message}]},
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            if ev.get("type") == "content_block_delta":
                                tok = ev.get("delta", {}).get("text", "")
                                if tok:
                                    yield tok
                        except json.JSONDecodeError:
                            pass

    elif provider == "google":
        key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            yield _no_key(provider)
            return
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:streamGenerateContent?alt=sse&key={key}")
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}],
            }) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            tok = ev["candidates"][0]["content"]["parts"][0].get("text", "")
                            if tok:
                                yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    else:
        yield (f"No LLM provider configured (MODEL_PROVIDER='{provider}'). "
               "Set it to xai, openai, anthropic or google in `.env`. "
               "Slash-commands like `/pipeline` still work without a key.")


def _no_key(provider: str) -> str:
    env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY",
           "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}[provider]
    return (f"⚠ No **{env}** set, so free-form chat is disabled. "
            "Add it to `.env` and restart. Meanwhile, slash-commands "
            "(`/pipeline`, `/leads`, `/kpi` …) work without any key.")
