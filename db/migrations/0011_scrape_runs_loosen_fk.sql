-- scrape_jobs is Job-state for Metabase; its rows can come and go
-- (cleanup jobs, dashboard rewrites).  Rate data in scrape_runs should
-- not be held hostage to that retention.  Drop the FK but keep the
-- column (scrape_runs.scrape_job_id remains useful for dashboard JOINs
-- when both sides happen to exist).

ALTER TABLE scrape_runs
    DROP CONSTRAINT IF EXISTS scrape_runs_scrape_job_id_fkey;
