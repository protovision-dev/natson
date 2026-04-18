"""Lazy Postgres connection for the scraper.

Reads creds from env (POSTGRES_HOST/PORT/DB/USER/PASSWORD).  When any
required piece is missing, `get_conn()` returns None so callers can
degrade gracefully.  Within docker-compose, POSTGRES_HOST defaults to
the service name `postgres`.
"""
from __future__ import annotations

import os
import sys

try:
    import psycopg
    from psycopg import Connection
except Exception:  # pragma: no cover
    psycopg = None
    Connection = None  # type: ignore

_conn: "Connection | None" = None
_warned_once = False


def _env() -> dict[str, str]:
    return {
        "host": os.environ.get("POSTGRES_HOST", "postgres"),
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "dbname": os.environ.get("POSTGRES_DB", ""),
        "user": os.environ.get("POSTGRES_USER", ""),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
    }


def pg_configured() -> bool:
    e = _env()
    return bool(psycopg and e["dbname"] and e["user"] and e["password"])


def get_conn() -> "Connection | None":
    """Return a live connection or None if not configured / unreachable."""
    global _conn, _warned_once
    if _conn is not None and not _conn.closed:
        return _conn
    if not pg_configured():
        if not _warned_once:
            print("[db] Postgres not configured — skipping DB writes", file=sys.stderr)
            _warned_once = True
        return None
    try:
        e = _env()
        _conn = psycopg.connect(
            host=e["host"], port=e["port"],
            dbname=e["dbname"], user=e["user"], password=e["password"],
            autocommit=True, connect_timeout=5,
        )
        return _conn
    except Exception as ex:  # pragma: no cover
        if not _warned_once:
            print(f"[db] cannot connect to Postgres: {ex} — skipping DB writes", file=sys.stderr)
            _warned_once = True
        _conn = None
        return None


def close_conn() -> None:
    global _conn
    if _conn and not _conn.closed:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None
