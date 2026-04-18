-- Bootstrap the first 9 months of rate_observations partitions.
-- Postgres refuses to insert a row if the matching monthly partition
-- doesn't exist, so we need at least one month ahead of the current
-- date pre-created before the first scrape ingests.
--
-- After this, 0007 schedules pg_cron to call ensure_rate_obs_partitions()
-- monthly so the window rolls forward automatically.
--
-- Covers 2026-04-01 through 2026-12-31 (9 partitions).  Idempotent —
-- each uses CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS rate_observations_2026_04 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_05 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_06 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_07 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_08 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_09 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_10 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_11 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE IF NOT EXISTS rate_observations_2026_12 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');
