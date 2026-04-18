-- Self-rolling monthly partitions for rate_observations.
-- Requires postgresql-16-cron in the postgres image and
-- `shared_preload_libraries = 'pg_cron'` in postgres.conf
-- (handled by the custom postgres/ image + postgres/postgresql.conf).
-- If the library isn't preloaded, db/migrate.sh refuses to apply this
-- file with an explicit recovery message.

CREATE EXTENSION IF NOT EXISTS pg_cron;

-- ---------------------------------------------------------------------
-- ensure_rate_obs_partitions(months_forward)
-- Creates (if missing) monthly partitions from the current month
-- through the current month + months_forward.  Idempotent.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ensure_rate_obs_partitions(months_forward INT DEFAULT 9)
RETURNS VOID AS $$
DECLARE
    start_month DATE := date_trunc('month', CURRENT_DATE)::DATE;
    i       INT;
    p_start DATE;
    p_end   DATE;
    p_name  TEXT;
BEGIN
    FOR i IN 0..months_forward LOOP
        p_start := start_month + (i || ' month')::INTERVAL;
        p_end   := p_start + INTERVAL '1 month';
        p_name  := 'rate_observations_' || to_char(p_start, 'YYYY_MM');
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF rate_observations '
            'FOR VALUES FROM (%L) TO (%L)',
            p_name, p_start, p_end
        );
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------
-- Re-schedulable: drop any prior job with this name, then register.
-- Cron timezone defaults to UTC.  Runs at 00:00 UTC on the 1st of every
-- month and pre-creates the next 9 months' partitions (idempotent).
-- ---------------------------------------------------------------------
DO $$
BEGIN
    PERFORM cron.unschedule(jobid)
      FROM cron.job
     WHERE jobname = 'ensure-rate-obs-partitions';
END
$$;

SELECT cron.schedule(
    'ensure-rate-obs-partitions',
    '0 0 1 * *',
    $cron$ SELECT ensure_rate_obs_partitions(9); $cron$
);

-- ---------------------------------------------------------------------
-- Run once on install so partitions for stale months roll forward
-- immediately without waiting for the first cron tick.
-- ---------------------------------------------------------------------
SELECT ensure_rate_obs_partitions(9);
