"""FastCRM public reads and token-gated integration writes."""

import db

from .api_core import Resource, SQLiteBackend, create_sqlite_api

RESOURCES = (
    Resource("contacts", "contacts", "Contacts", "People associated with customer organisations.", search_fields=("first_name", "last_name", "email", "job_title")),
    Resource("companies", "organizations", "Companies", "Customer and prospect organisation records.", search_fields=("name", "industry", "territory")),
    Resource("leads", "leads", "Leads", "Unqualified and qualified sales leads.", write_fields=("first_name", "last_name", "organization", "email", "mobile", "status", "source", "industry", "territory"), search_fields=("first_name", "last_name", "organization", "email", "status")),
    Resource("opportunities", "deals", "Opportunities", "Pipeline opportunities and their commercial stages.", search_fields=("stage", "source", "industry", "next_step")),
)

backend = SQLiteBackend(db.DB_PATH, RESOURCES, initialize=db.init_schema)
api = create_sqlite_api(
    product="FastCRM", version="1.0.0",
    description="Open integration access to FastCRM customer and pipeline data.",
    base_url="https://crm.fastsme.com", backend=backend, resources=RESOURCES,
)
