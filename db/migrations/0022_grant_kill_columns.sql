-- Allow natson_auth to mark a stuck scrape as failed via the new
-- /api/jobs/[id]/kill endpoint. Same column-level grant pattern as
-- 0021 (resumed_to_job_id) — keeps natson_auth from being able to
-- rewrite progress, hotels_done, spec, started_at, etc.
--
-- Wrapped in a role-exists guard for fresh-install ordering (bootstrap
-- creates the role; on first migrate the role may not exist yet).
-- bootstrap-app-roles.sh applies the same GRANTs unconditionally so
-- both orderings work.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'natson_auth') THEN
        GRANT UPDATE (state, completed_at, exit_code, last_line)
            ON public.scrape_jobs TO natson_auth;
    ELSE
        RAISE NOTICE 'natson_auth role missing; skip grants (run db/bootstrap-app-roles.sh first or after this migration)';
    END IF;
END
$$;
