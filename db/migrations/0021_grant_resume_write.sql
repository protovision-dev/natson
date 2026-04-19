-- Allow natson_auth to write the resumed_to_job_id column on
-- scrape_jobs. The web service's resume API needs to mark the failed
-- parent job once the successor is spawned, but it doesn't have any
-- other write access on public — natson_ro is read-only.
--
-- We grant a column-level UPDATE so the role still can't touch
-- anything else on scrape_jobs (no rewriting state, hotels_done,
-- last_line, etc. from the web tier).
--
-- Refresh the bootstrap script too: db/bootstrap-app-roles.sh applies
-- this same GRANT for fresh installs.

GRANT SELECT ON public.scrape_jobs TO natson_auth;
GRANT UPDATE (resumed_to_job_id) ON public.scrape_jobs TO natson_auth;
