# FastCRM Roadmap — Frappe CRM feature comparison

FastCRM ports the **core** of [Frappe CRM](https://github.com/frappe/crm) to a
FastHTML demonstrator. This document records what was analysed in the upstream
repo (its DocType model + frontend), what FastCRM implements today, and what is
deliberately deferred — so the gap is explicit, not hidden.

Upstream analysed: `frappe/crm` (`crm/fcrm/doctype/*`), ~40 doctypes.

## Implemented in FastCRM ✅

| Capability | Upstream doctype(s) | FastCRM |
|---|---|---|
| Leads with status funnel | `CRM Lead`, `CRM Lead Status` | `leads` table, 6-status segment |
| Deals + pipeline stages | `CRM Deal`, `CRM Deal Status` | `deals` table, 7-stage **Kanban** |
| Organizations | `CRM Organization` | `organizations`, ranked by won value |
| Contacts | `Contact`, `CRM Contacts` | `contacts`, per-org |
| Tasks | `CRM Task` | `tasks`, status/priority, linked to deals |
| Notes | `FCRM Note` | `notes` + activity timeline |
| Activity timeline | status/`CRM Status Change Log`, comments | `activities` feed per lead/deal |
| Call logs | `CRM Call Log` | `call_logs` (synthetic) |
| Lead sources / industries / territories | `CRM Lead Source`, `CRM Industry`, `CRM Territory` | vocabularies in `db.py` |
| Dashboard / KPIs | `CRM Dashboard` | KPI cards + pipeline funnel |
| **Saved / custom views** | `CRM View Settings` | named lead filters (status/source/owner/sort) as chips |
| **Email composer** | `CRM Communication` | compose-email card on deals & leads → logs to timeline |
| **AI assistant over CRM data** | *(not in upstream)* | new — grounded multi-provider chat |

## Near-term roadmap 🔜

Features present upstream and worth adding to the demonstrator next:

1. ✅ **Write operations & inline editing** (done) — upstream is fully CRUD; FastCRM was
   read-only over synthetic data. Add HTMX-driven create/edit for leads, deals,
   tasks, notes (stage drag-and-drop on the Kanban via `hx-post`).
2. ✅ **Custom & saved views** (done) — the leads list has a filter toolbar
   (status, source, owner, search, sort); the current filter set can be saved as
   a named view and re-applied or deleted from a chip bar (`saved_views` table).
   Column-pick and kanban views are still to come.
3. ✅ **Email composer** (done) — a compose-email card on both deal and lead
   detail (To / Subject / Body) records an `email` activity on the timeline
   (`db.log_email`). Real SMTP send + inbound threading remains out of scope.
4. **SLA tracking** — `CRM Service Level Agreement` / `…Priority` /
   `…Rolling Response Time` drive first-response/resolution timers. Add response
   SLAs with a "due / breached" indicator.
5. **Products & quotations** — `CRM Product(s)`, deal totals/net-total. Add a
   line-item products table and a deal value calculator.
6. **Notifications** — `CRM Notification` + invitations. Add an in-app
   notification feed.

## Later / out-of-scope for a demonstrator 🗓️

- **Telephony integrations** — `CRM Twilio Settings`, `CRM Exotel Settings`,
  `CRM Telephony Agent` (click-to-call, recordings). FastCRM keeps call logs as
  static records.
- **Lead syncing** — Facebook Lead Forms (`facebook_lead_form`, `facebook_page`,
  `lead_sync_source`, `failed_lead_sync_log`) and ERPNext bridge
  (`erpnext_crm_settings`). External-integration heavy.
- **Form scripts / custom fields** — `CRM Form Script`, `CRM Fields Layout`
  (runtime low-code customisation) — a Frappe-framework feature, not ported.
- **Sales hierarchy & assignment rules** — `CRM Sales Hierarchy`, holiday lists,
  service days.
- **Multi-currency** with live exchange rates.

## Design notes

FastCRM intentionally **collapses** Frappe's normalised model (every status is
its own doctype upstream) into `TEXT` columns + Python vocabularies in `db.py`.
This keeps the demonstrator legible while preserving the same domain language.
The reusable `scripts/frappe_doctype_to_schema.py` regenerates a starting schema
from any upstream doctype if you want to widen coverage.
