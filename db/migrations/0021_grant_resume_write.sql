-- Allow natson_auth to write the resumed_to_job_id column on
-- scrape_jobs. The web service's resume API needs to mark the failed
-- parent job once the successor is spawned, but it doesn't have any
-- other write access on public — natson_ro is read-only.
--
-- We grant a column-level UPDATE so the role still can't touch
-- anything else on scrape_jobs (no rewriting state, hotels_done,
-- last_line, etc. from the web tier).
--
-- Idempotent + tolerant of fresh installs: the grants are wrapped in
-- a role-existence check because on a brand-new DB the role isn't
-- created until db/bootstrap-app-roles.sh runs. db/bootstrap-app-roles.sh
-- applies the same GRANTs unconditionally, so order is:
--   - fresh install: migrate.sh up (this is a no-op) → bootstrap-app-roles.sh (does the grants)
--   - existing install: bootstrap was already run → migrate.sh up applies the grants here
-- Either way, the grants land. Without this guard, a fresh prod
-- migration aborts with "role natson_auth does not exist".

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'natson_auth') THEN
        GRANT SELECT ON public.scrape_jobs TO natson_auth;
        GRANT UPDATE (resumed_to_job_id) ON public.scrape_jobs TO natson_auth;
    ELSE
        RAISE NOTICE 'natson_auth role missing; skip grants (run db/bootstrap-app-roles.sh first or after this migration)';
    END IF;
END
$$;
