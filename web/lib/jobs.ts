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
      do_refresh, refresh_only, exit_code, last_line
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
      do_refresh, refresh_only, exit_code, last_line
    FROM scrape_jobs WHERE job_id = ${jobId}
  `;
  return rows[0] ?? null;
}

export async function subjectCodesToSubscriptionIds(
  subjectCodes: string[],
): Promise<string[]> {
  if (subjectCodes.length === 0) return [];
  const rows = await sql<{ subscription_id: string }[]>`
    SELECT subscription_id::text FROM subject_hotels
    WHERE internal_code = ANY(${subjectCodes})
      AND subscription_id IS NOT NULL
  `;
  return rows.map((r) => r.subscription_id);
}
