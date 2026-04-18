-- Sweep phantom 'running'/'starting' scrape_jobs rows.
--
-- If a scrape process is killed (OOM, host crash, docker kill) mid-run,
-- StatusWriter.finish() never executes and the scrape_jobs row stays
-- stuck at state='running'.  The Active-scrapes dashboard would then
-- show a "running" row forever.
--
-- This runs hourly via pg_cron and demotes anything that hasn't been
-- updated in >2h to state='failed' with a note.  2h is deliberately
-- longer than any healthy portfolio scrape (booking ran 32m, brand ran
-- 60m) and matches LOCK_STALE_AFTER_S in the login daemon.

CREATE OR REPLACE FUNCTION sweep_stale_scrape_jobs(stale_after_s INT DEFAULT 7200)
RETURNS INT AS $$
DECLARE
    swept_count INT;
BEGIN
    UPDATE scrape_jobs
       SET state        = 'failed',
           completed_at = NOW(),
           exit_code    = COALESCE(exit_code, -1),
           last_line    = COALESCE(last_line, '')
                          || ' [swept as stale by sweep_stale_scrape_jobs]'
     WHERE state IN ('starting', 'running')
       AND updated_at < NOW() - make_interval(secs => stale_after_s);
    GET DIAGNOSTICS swept_count = ROW_COUNT;
    RETURN swept_count;
END;
$$ LANGUAGE plpgsql;

-- Idempotent schedule.
DO $$
BEGIN
    PERFORM cron.unschedule(jobid)
      FROM cron.job
     WHERE jobname = 'sweep-stale-scrape-jobs';
END
$$;

SELECT cron.schedule(
    'sweep-stale-scrape-jobs',
    '5 * * * *',   -- 5 min past every hour
    $cron$ SELECT sweep_stale_scrape_jobs(7200); $cron$
);

-- Run once on install to clean any existing phantoms.
SELECT sweep_stale_scrape_jobs(7200);
