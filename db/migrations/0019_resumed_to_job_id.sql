-- Track which failed job each resume produced, so the UI can hide the
-- "Resume" button once it's been clicked. Persists across page reloads
-- (in-memory disabled-state was getting reset on every refresh).

ALTER TABLE scrape_jobs
    ADD COLUMN IF NOT EXISTS resumed_to_job_id TEXT NULL;

-- Recreate recent_scrapes view to expose the new column.
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
    last_line,
    resumed_to_job_id
FROM scrape_jobs
ORDER BY started_at DESC
LIMIT 200;
