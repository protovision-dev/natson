"""Postgres data-access layer.

Phase 3+: scrape_jobs (job metadata for Metabase).
Phase 5:  rate_cells, refreshes, etc. (schema from user).

The connection is opened lazily and held for the life of one process.
When Postgres is unavailable or creds aren't set, writes silently
no-op — the filesystem status.json is still authoritative, so a
missing DB never fails a running scrape.
"""
from .connection import get_conn, close_conn, pg_configured
from .jobs import upsert_job_status
