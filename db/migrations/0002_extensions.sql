-- Extensions needed by the rate-tracking schema.
-- pg_trgm    : trigram index for fuzzy hotel-name search
-- pg_cron    : scheduled jobs (used by 0007). CREATE EXTENSION only
--              works when pg_cron is in shared_preload_libraries; see
--              postgres/postgresql.conf. 0007 does the extension create
--              itself so this file succeeds even on a postgres image
--              that predates the pg_cron rollout.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
