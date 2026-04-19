import { getAuthPool } from "./auth";
import { sql } from "./db";

export type JobSpec = {
  hotels: string[];
  ota: "bookingdotcom" | "branddotcom";
  los: number;
  persons: number;
  do_refresh: boolean;
  checkin_dates: string[];
  raw_dates_expr?: string;
};

export type ResumePayload = {
  hotels: string[];
  dates: string;
  ota: "bookingdotcom" | "branddotcom";
  los: number;
  persons: number;
  refresh: boolean;
};

export type ResumeError =
  | { kind: "not_found" }
  | { kind: "not_failed"; state: string }
  | { kind: "already_complete" }
  | { kind: "already_resumed"; resumed_to_job_id: string }
  | { kind: "bad_spec"; reason: string };

/**
 * Compute the payload for a resumed run from a failed job's stored
 * spec + its progress count. Re-runs the in-progress hotel
 * (`hotels_done` index, since `mark_hotel_done` is the LAST step per
 * iteration) and every hotel after it.
 *
 * Pure function so the slice math is testable without a DB.
 */
export function buildResumePayload(
  spec: JobSpec,
  hotels_done: number,
): { ok: true; payload: ResumePayload } | { ok: false; error: ResumeError } {
  if (!Array.isArray(spec.hotels) || spec.hotels.length === 0) {
    return { ok: false, error: { kind: "bad_spec", reason: "spec.hotels empty" } };
  }
  if (
    !Array.isArray(spec.checkin_dates) ||
    spec.checkin_dates.length === 0 ||
    typeof spec.checkin_dates[0] !== "string" ||
    typeof spec.checkin_dates[spec.checkin_dates.length - 1] !== "string"
  ) {
    return { ok: false, error: { kind: "bad_spec", reason: "spec.checkin_dates empty" } };
  }

  // Clamp negative / overflow just in case the DB column drifts.
  const startIdx = Math.max(0, Math.min(hotels_done, spec.hotels.length));
  const remaining = spec.hotels.slice(startIdx);
  if (remaining.length === 0) {
    return { ok: false, error: { kind: "already_complete" } };
  }

  // Pin to the original calendar window via explicit YYYY-MM-DD range.
  // Avoids re-evaluating "rolling:2" against today and silently
  // shifting the scrape window.
  const dates = `${spec.checkin_dates[0]}:${spec.checkin_dates[spec.checkin_dates.length - 1]}`;

  return {
    ok: true,
    payload: {
      hotels: remaining,
      dates,
      ota: spec.ota,
      los: spec.los,
      persons: spec.persons,
      refresh: spec.do_refresh,
    },
  };
}

/** Pull the failed job's spec + progress directly from Postgres.
 *  Refuses if the job already has a successor recorded so a double-
 *  click on the UI Resume button can't spawn duplicate scrapes. */
export async function fetchFailedJobForResume(
  jobId: string,
): Promise<
  | { ok: true; spec: JobSpec; hotels_done: number; hotels_total: number }
  | { ok: false; error: ResumeError }
> {
  const rows = await sql<
    {
      state: string;
      hotels_done: number;
      hotels_total: number;
      spec: JobSpec | null;
      resumed_to_job_id: string | null;
    }[]
  >`
    SELECT state, hotels_done, hotels_total, spec, resumed_to_job_id
    FROM scrape_jobs
    WHERE job_id = ${jobId}
  `;
  const row = rows[0];
  if (!row) return { ok: false, error: { kind: "not_found" } };
  if (row.state !== "failed") {
    return { ok: false, error: { kind: "not_failed", state: row.state } };
  }
  if (row.resumed_to_job_id) {
    return {
      ok: false,
      error: { kind: "already_resumed", resumed_to_job_id: row.resumed_to_job_id },
    };
  }
  if (!row.spec) {
    return { ok: false, error: { kind: "bad_spec", reason: "spec column null" } };
  }
  return {
    ok: true,
    spec: row.spec,
    hotels_done: row.hotels_done,
    hotels_total: row.hotels_total,
  };
}

/** Mark the original failed job as resumed → linking to the new job's
 *  id. Idempotent via the WHERE-IS-NULL guard. Uses the auth-schema
 *  pool because natson_ro can't UPDATE; migration 0021 grants
 *  natson_auth a column-level UPDATE on scrape_jobs.resumed_to_job_id
 *  specifically (no broader writes). */
export async function markResumed(jobId: string, newJobId: string): Promise<number> {
  const r = await getAuthPool().query(
    `UPDATE scrape_jobs
        SET resumed_to_job_id = $1
      WHERE job_id = $2
        AND resumed_to_job_id IS NULL`,
    [newJobId, jobId],
  );
  return r.rowCount ?? 0;
}
