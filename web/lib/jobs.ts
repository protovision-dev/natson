import { sql } from "./db";

export type ActiveJob = {
  job_id: string;
  state: string;
  started_at: string;
  updated_at: string;
  running_seconds: number;
  ota: string | null;
  hotels_total: number;
  hotels_done: number;
  hotels_failed: number;
  current_hotel: string | null;
  current_step: string | null;
  checkin_from: string | null;
  checkin_to: string | null;
  do_refresh: boolean | null;
  refresh_only: boolean | null;
  last_line: string | null;
};

export type RecentJob = {
  job_id: string;
  state: string;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number;
  ota: string | null;
  hotels_total: number;
  hotels_done: number;
  hotels_failed: number;
  checkin_from: string | null;
  checkin_to: string | null;
  do_refresh: boolean | null;
  refresh_only: boolean | null;
  exit_code: number | null;
  last_line: string | null;
  resumed_to_job_id: string | null;
};

export async function fetchActiveJobs(): Promise<ActiveJob[]> {
  const rows = await sql<ActiveJob[]>`
    SELECT
      job_id, state,
      started_at::text, updated_at::text,
      running_seconds, ota,
      hotels_total, hotels_done, hotels_failed,
      current_hotel, current_step,
      checkin_from::text, checkin_to::text,
      do_refresh, refresh_only, last_line
    FROM active_scrapes
  `;
  return [...rows];
}

export async function fetchRecentJobs(limit = 50): Promise<RecentJob[]> {
  const rows = await sql<RecentJob[]>`
    SELECT
      job_id, state,
      started_at::text, completed_at::text,
      duration_seconds, ota,
      hotels_total, hotels_done, hotels_failed,
      checkin_from::text, checkin_to::text,
      do_refresh, refresh_only, exit_code, last_line,
      resumed_to_job_id
    FROM recent_scrapes LIMIT ${limit}
  `;
  return [...rows];
}

export async function fetchJob(jobId: string): Promise<RecentJob | null> {
  const rows = await sql<RecentJob[]>`
    SELECT
      job_id, state, started_at::text, completed_at::text,
      CASE WHEN completed_at IS NOT NULL
           THEN EXTRACT(EPOCH FROM (completed_at - started_at))::INT
           ELSE EXTRACT(EPOCH FROM (NOW() - started_at))::INT
      END AS duration_seconds,
      ota, hotels_total, hotels_done, hotels_failed,
      checkin_from::text, checkin_to::text,
      do_refresh, refresh_only, exit_code, last_line,
      resumed_to_job_id
    FROM scrape_jobs WHERE job_id = ${jobId}
  `;
  return rows[0] ?? null;
}

/** Force a stuck running/starting job to 'failed' in the DB so the
 *  Resume flow becomes available. Does NOT kill any underlying OS
 *  process — assumes the process is already dead (the common case
 *  when this is needed). Returns the row count: 1 = killed, 0 = job
 *  was already terminal or doesn't exist.
 *
 *  Uses the auth-schema pool (natson_auth) which has column-level
 *  UPDATE on the four columns we touch (granted in migration 0022).
 */
export async function markJobFailed(jobId: string, reason: string): Promise<number> {
  const { getAuthPool } = await import("./auth");
  const r = await getAuthPool().query(
    `UPDATE scrape_jobs
        SET state        = 'failed',
            completed_at = NOW(),
            exit_code    = COALESCE(exit_code, -1),
            last_line    = $2
      WHERE job_id = $1
        AND state IN ('starting','running')`,
    [jobId, reason],
  );
  return r.rowCount ?? 0;
}

export async function subjectCodesToSubscriptionIds(subjectCodes: string[]): Promise<string[]> {
  if (subjectCodes.length === 0) return [];
  const rows = await sql<{ subscription_id: string }[]>`
    SELECT subscription_id::text FROM subject_hotels
    WHERE internal_code = ANY(${subjectCodes})
      AND subscription_id IS NOT NULL
  `;
  return rows.map((r) => r.subscription_id);
}
