-- One row per Lighthouse scrape job.  run_job.py upserts on every state
-- transition so Metabase can show live progress across concurrent jobs.
--
-- `state` lifecycle:  starting → running → (completed | failed)
-- `spec` is the resolved Job JSON (stringified dates, all URL params).

CREATE TABLE IF NOT EXISTS scrape_jobs (
    job_id          TEXT        PRIMARY KEY,
    state           TEXT        NOT NULL CHECK (state IN ('starting','running','completed','failed')),
    started_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    pid             INTEGER,
    host            TEXT,
    hotels_total    INTEGER     NOT NULL,
    hotels_done     INTEGER     NOT NULL DEFAULT 0,
    hotels_failed   INTEGER     NOT NULL DEFAULT 0,
    current_hotel   TEXT,
    current_step    TEXT,
    ota             TEXT,
    checkin_from    DATE,
    checkin_to      DATE,
    do_refresh      BOOLEAN,
    refresh_only    BOOLEAN,
    last_line       TEXT,
    exit_code       INTEGER,
    spec            JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS scrape_jobs_state_idx        ON scrape_jobs (state);
CREATE INDEX IF NOT EXISTS scrape_jobs_started_at_idx   ON scrape_jobs (started_at DESC);
CREATE INDEX IF NOT EXISTS scrape_jobs_ota_idx          ON scrape_jobs (ota);

-- Convenience view for Metabase: everything not yet done.
CREATE OR REPLACE VIEW active_scrapes AS
SELECT
    job_id,
    state,
    started_at,
    updated_at,
    EXTRACT(EPOCH FROM (NOW() - started_at))::INT AS running_seconds,
    ota,
    hotels_total,
    hotels_done,
    hotels_failed,
    current_hotel,
    current_step,
    checkin_from,
    checkin_to,
    do_refresh,
    refresh_only,
    last_line
FROM scrape_jobs
WHERE state IN ('starting', 'running')
ORDER BY started_at DESC;

-- And a recent-history view for the dashboard's "last 50 jobs" table.
CREATE OR REPLACE VIEW recent_scrapes AS
SELECT
    job_id,
    state,
    started_at,
    completed_at,
    CASE WHEN completed_at IS NOT NULL
         THEN EXTRACT(EPOCH FROM (completed_at - started_at))::INT
         ELSE EXTRACT(EPOCH FROM (NOW() - started_at))::INT
    END AS duration_seconds,
    ota,
    hotels_total,
    hotels_done,
    hotels_failed,
    checkin_from,
    checkin_to,
    do_refresh,
    refresh_only,
    exit_code,
    last_line
FROM scrape_jobs
ORDER BY started_at DESC
LIMIT 200;
