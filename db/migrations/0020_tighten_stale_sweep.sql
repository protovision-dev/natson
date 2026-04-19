-- Tighten the stale-scrape-job sweep cadence.
--
-- Old config (0014): hourly cron, 2-hour threshold. Worst case: a
-- killed process sits as "running" for ~3h before being demoted.
-- That's what bit us during today's docker recovery — the brand
-- scrape sat stale for 68m before we manually marked it failed.
--
-- New config: run every 5 minutes. Same 2-hour threshold (any tighter
-- risks falsely sweeping a healthy scrape during the ~5-min Lighthouse
-- refresh-polling step where status.set() isn't called between
-- iterations).
--
-- Worst-case detection latency: ~2h5m. Was ~3h.
--
-- Follow-up not in this migration: have the scraper's polling loop
-- write a status.set() every 30s as a heartbeat — that would let us
-- safely cut the threshold to 5m and detect dead processes in near-
-- real-time. Lives in scraper code, not in the DB layer.

DO $$
BEGIN
    PERFORM cron.unschedule(jobid)
      FROM cron.job
     WHERE jobname = 'sweep-stale-scrape-jobs';
END
$$;

SELECT cron.schedule(
    'sweep-stale-scrape-jobs',
    '*/5 * * * *',
    $cron$ SELECT sweep_stale_scrape_jobs(7200); $cron$
);
