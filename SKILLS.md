# Skills

Two things live here: a **capability reference** for FastCRM, and a reusable
**Frappe → FastHTML / HTMX migration playbook** with generic scripts that carry
over to the other apps in `fasthtml-oss-migrations`.

---

## Part 1 — FastCRM capabilities

**Entry:** `python web_app.py` → http://localhost:5006
(login `admin@fastcrm.example` / `FastCRM2026$`, override via `.env`).

3-pane FastHTML layout: left nav · center work area · right AI rail.

### Pages

| View | Route | What it shows |
|---|---|---|
| Dashboard | `/` | KPI cards (open deals, won value, win rate, new leads, open tasks), pipeline funnel by stage, top open deals, live activity feed |
| Deals | `/deals` | Kanban board across the 7 pipeline stages; each card links to a deal |
| Deal detail | `/deals/{id}` | Deal facts, primary contact, tasks, full activity timeline |
| Leads | `/leads?status=&q=` | Status-segmented, searchable lead register |
| Lead detail | `/leads/{id}` | Lead facts + activity |
| Tasks | `/tasks?status=` | Open / by-status task list linked back to deals |
| Contacts | `/contacts?q=` | Searchable people directory |
| Organizations | `/organizations` | Companies ranked by won value, with contact/deal counts |
| AI Assistant | `/ai` | Landing page; the chat itself is the right rail |
| User Guide | `/guide` | In-app how-to |

### Data model (`db.py`)

SQLite, collapsed from Frappe CRM's doctypes:
`users · organizations · contacts · leads · deals · tasks · notes · activities ·
call_logs · chat_messages`. Vocabularies (`LEAD_STATUSES`, `DEAL_STAGES`,
`TASK_STATUSES`, …) live at the top of `db.py` so the seed and the UI never drift.
`db.py` also exposes typed read helpers (`kpis()`, `pipeline_by_stage()`,
`deal()`, `activities_for()`, …) shared by both the views and the AI tools.

Rebuild the synthetic database any time:

```bash
python seed.py            # deterministic — same demo data every run, no PII
```

### AI assistant (`web/ai.py`)

- **Slash-commands** resolve locally against SQLite — instant, **no API key**:
  `/pipeline` `/deals [stage]` `/leads [status]` `/tasks` `/kpi` `/org <name>` `/help`.
- **Free-form chat** streams from a configurable provider, grounded with a live
  `crm_snapshot()` injected into the system prompt so answers reflect real data.
  Set `MODEL_PROVIDER` (`xai` | `openai` | `anthropic` | `google`) + the matching
  key in `.env`. Streaming is plain SSE consumed by ~40 lines of vanilla JS in
  `layout.py` — no JS framework.

---

## Part 2 — Frappe → FastHTML migration playbook

A repeatable recipe for turning a Frappe app into a compact FastHTML
demonstrator. FastCRM was built with exactly these steps.

### 1. Mine the source schema

Frappe models are **DocTypes** — JSON files under
`<app>/<module>/doctype/<name>/<name>.json`. List and convert them:

```bash
git clone --depth 1 https://github.com/frappe/<app>.git /tmp/frappe-<app>
python scripts/frappe_doctype_to_schema.py /tmp/frappe-<app>   # prints suggested DDL
```

`scripts/frappe_doctype_to_schema.py` (stdlib-only, copy it between repos)
maps Frappe fieldtypes → SQLite columns, resolves `Link`/`Dynamic Link` targets,
and skips layout-only fields (`Section Break`, `Column Break`, `Table`, …).
Hand-edit the output into a lean relational core — you rarely want every field.

Default fixture values (statuses, stages) live in each doctype's
`test_records.json` or its controller `.py`; copy these so your vocabularies match.

### 2. Collapse, don't replicate

Frappe normalises aggressively (every status is its own doctype). For a
demonstrator, fold these into `TEXT` columns + a Python list of allowed values.
Keep only the entities a user actually navigates.

### 3. Build the FastHTML shell

- `fast_app(pico=False, secret_key=..., hdrs=[Style(CSS)])`; **don't** double-load
  htmx (fast_app already includes it).
- One `page(active, env, user, thread, *content)` helper wraps every view in the
  3-pane layout. Views return **tuples of FT components**, never strings.
- Auth: a `Beforeware`-free `_guard(session, active, builder)` that redirects to
  `/login` when `session["user"]` is missing keeps routes one-liners.
- Use `RedirectResponse(url, status_code=303)` after POSTs.

### 4. HTMX over JavaScript

- Navigation is plain `<a href>`; partial updates use `hx_get`/`hx_post` +
  `hx_target`/`hx_swap`. Search/filter forms are GET forms posting to the same route.
- Reach for vanilla JS only for streaming (SSE reader) — and keep it in one place.
- Stream LLM tokens as `data: {json}\n\n`; a `StreamingResponse(gen(),
  media_type="text/event-stream")` plus a small `fetch().getReader()` loop is the
  whole pattern (see `web/ai.py` + `LAYOUT_JS`).

### 5. Synthetic data only

Generate everything with a **fixed RNG seed** (`seed.py`) so demos are
reproducible and contain no real people or companies. The app self-seeds on first
boot (`_ensure_db()` in `web_app.py`) so a fresh clone just runs.

### 6. Multi-provider LLM, key-optional

Copy the `_provider_stream()` dispatch in `web/ai.py`: xAI and OpenAI share the
chat-completions shape; Anthropic uses `/v1/messages`; Google uses
`:streamGenerateContent?alt=sse`. Always degrade gracefully — slash-commands and
the rest of the app must work with **no** API key.

### 7. Capture the demo

Run the app, drive it with **Playwright MCP**, screenshot each screen into
`docs/demo/frames/NN-name.png`, then:

```bash
bash scripts/build_demo_gif.sh        # frames → docs/demo/<app>-walkthrough.gif
```

`build_demo_gif.sh` is generic (ImageMagick `convert`, ffmpeg fallback); only the
output name changes per repo. Embed the GIF at the top of `README.md`.

### 8. Ship deploy paths

`.env.sample` (every key, secrets blank) · `Dockerfile` (python:3.12-slim, seed
on first boot) · `docker-compose.yml` (named volume at `/data` so the DB outlives
image rebuilds) · `requirements.txt` pinned to the four runtime deps.

### Reusable assets in this repo

| File | Reuse |
|---|---|
| `scripts/frappe_doctype_to_schema.py` | DocType JSON → SQLite DDL (any Frappe app) |
| `scripts/build_demo_gif.sh` | PNG frames → looping demo GIF |
| `web/layout.py` | 3-pane shell + CSS design tokens + SSE chat JS |
| `web/ai.py` `_provider_stream()` | 4-provider streaming chat dispatch |
| `seed.py` structure | deterministic synthetic-data generator |
