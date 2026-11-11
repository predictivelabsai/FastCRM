"""Idempotent contact import for FastCRM (CSV / JSON rows -> contacts).

Rows use the columns: first_name, last_name, primary_email, other_emails
(';'-separated), job_title, company, company_website, linkedin_url, website,
linkedin_confidence, notes. Every imported contact and organization is owned
by ``owner_email``; LinkedIn/website/extra emails go into a tagged note owned
by the same user. Re-running with the same tag updates rather than duplicates
(contacts are matched by any of their emails, organizations by name per owner).

CLI:  python importer.py contacts.csv --owner you@example.com [--tag T] [--apply]
"""
from __future__ import annotations

import csv
import sys

import db

FIELDS = ("first_name", "last_name", "primary_email", "other_emails", "job_title",
          "company", "company_website", "linkedin_url", "website",
          "linkedin_confidence", "notes")


def _s(row, key):
    return (row.get(key) or "").strip()


def import_rows(rows, owner_email: str, owner_name: str = "", tag: str = "import",
                apply: bool = False) -> dict:
    db.init_schema()
    conn = db.connect()
    try:
        owner_email = owner_email.strip().lower()
        u = conn.execute("SELECT id FROM users WHERE lower(email)=?", (owner_email,)).fetchone()
        owner_id = u[0] if u else conn.execute(
            "INSERT INTO users(name,email) VALUES (?,?)",
            (owner_name or owner_email.split("@")[0], owner_email)).lastrowid
        stats = {"contacts_before": conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
                 "orgs_before": conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0],
                 "contacts_inserted": 0, "contacts_updated": 0,
                 "orgs_inserted": 0, "orgs_matched": 0, "skipped": 0}
        for row in rows:
            primary = _s(row, "primary_email").lower()
            if not primary:
                stats["skipped"] += 1
                continue
            org_id = None
            company = _s(row, "company")
            if company:
                o = conn.execute("SELECT id, website FROM organizations WHERE lower(name)=lower(?) AND owner_id=?",
                                 (company, owner_id)).fetchone()
                if o:
                    org_id = o[0]
                    stats["orgs_matched"] += 1
                    if _s(row, "company_website") and not o[1]:
                        conn.execute("UPDATE organizations SET website=? WHERE id=?",
                                     (_s(row, "company_website"), org_id))
                else:
                    org_id = conn.execute(
                        "INSERT INTO organizations(name,website,owner_id,created) VALUES (?,?,?,datetime('now'))",
                        (company, _s(row, "company_website") or None, owner_id)).lastrowid
                    stats["orgs_inserted"] += 1
            emails = [primary] + [e.strip().lower() for e in _s(row, "other_emails").split(";") if e.strip()]
            marks = ",".join("?" * len(emails))
            c = conn.execute(f"SELECT id FROM contacts WHERE lower(email) IN ({marks}) AND owner_id=?",
                             (*emails, owner_id)).fetchone()
            vals = (_s(row, "first_name") or None, _s(row, "last_name") or None, primary,
                    _s(row, "job_title") or None, org_id)
            if c:
                cid = c[0]
                conn.execute(
                    "UPDATE contacts SET first_name=COALESCE(?,first_name), last_name=COALESCE(?,last_name), "
                    "email=?, job_title=COALESCE(?,job_title), org_id=COALESCE(?,org_id) WHERE id=?",
                    (*vals, cid))
                stats["contacts_updated"] += 1
            else:
                cid = conn.execute(
                    "INSERT INTO contacts(first_name,last_name,email,job_title,org_id,owner_id,created) "
                    "VALUES (?,?,?,?,?,?,datetime('now'))", (*vals, owner_id)).lastrowid
                stats["contacts_inserted"] += 1
            lines = [f"Owner: {owner_email}"]
            if _s(row, "other_emails"):
                lines.append(f"Other emails: {_s(row, 'other_emails')}")
            if _s(row, "linkedin_url"):
                conf = _s(row, "linkedin_confidence")
                lines.append(f"LinkedIn: {_s(row, 'linkedin_url')}" + (f" (confidence {conf})" if conf else ""))
            if _s(row, "website"):
                lines.append(f"Website: {_s(row, 'website')}")
            if _s(row, "notes"):
                lines.append(f"Notes: {_s(row, 'notes')}")
            conn.execute("DELETE FROM notes WHERE ref_type='contact' AND ref_id=? AND title=?", (cid, tag))
            conn.execute("INSERT INTO notes(title,content,ref_type,ref_id,owner_id,created) "
                         "VALUES (?,?,?,?,?,datetime('now'))", (tag, "\n".join(lines), "contact", cid, owner_id))
        stats.update(
            contacts_after=conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
            orgs_after=conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0],
            owner_id=owner_id,
            contacts_owned=conn.execute("SELECT COUNT(*) FROM contacts WHERE owner_id=?", (owner_id,)).fetchone()[0],
            orgs_owned=conn.execute("SELECT COUNT(*) FROM organizations WHERE owner_id=?", (owner_id,)).fetchone()[0],
            notes_tagged=conn.execute("SELECT COUNT(*) FROM notes WHERE title=? AND owner_id=?", (tag, owner_id)).fetchone()[0],
            applied=apply)
        if apply:
            conn.commit()
        else:
            conn.rollback()
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--owner-name", default="")
    ap.add_argument("--tag", default="import")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    with open(a.csv, encoding="utf-8") as fh:
        print(import_rows(list(csv.DictReader(fh)), a.owner, a.owner_name, a.tag, a.apply))
    sys.exit(0)
