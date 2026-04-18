-- Tracks which migrations have been applied.  migrate.sh consults this
-- table before running each file and records successful applies here.
-- Idempotent: re-running is a no-op once the row exists.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,           -- "0001", "0002", ...
    filename    TEXT        NOT NULL,              -- "0001_schema_migrations.sql"
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version, filename)
VALUES ('0001', '0001_schema_migrations.sql')
ON CONFLICT (version) DO NOTHING;
