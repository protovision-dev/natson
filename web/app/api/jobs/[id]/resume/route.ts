import { NextResponse } from "next/server";
import { headers } from "next/headers";

import { auth } from "@/lib/auth";
import { isAdmin } from "@/lib/admin";
import { buildResumePayload, fetchFailedJobForResume, markResumed } from "@/lib/job-resume";

export const dynamic = "force-dynamic";

export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (!isAdmin(session.user.email)) {
    return NextResponse.json({ error: "Only admins can resume jobs" }, { status: 403 });
  }

  const { id } = await ctx.params;
  const fetched = await fetchFailedJobForResume(id);
  if (!fetched.ok) {
    const e = fetched.error;
    if (e.kind === "not_found") {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }
    if (e.kind === "not_failed") {
      return NextResponse.json(
        { error: `Job is ${e.state}, only failed jobs can be resumed` },
        { status: 409 },
      );
    }
    if (e.kind === "already_resumed") {
      return NextResponse.json(
        {
          error: `This job has already been resumed by ${e.resumed_to_job_id}`,
          resumed_to_job_id: e.resumed_to_job_id,
        },
        { status: 409 },
      );
    }
    return NextResponse.json(
      { error: `Bad spec: ${(e as { reason?: string }).reason ?? e.kind}` },
      { status: 500 },
    );
  }

  const built = buildResumePayload(fetched.spec, fetched.hotels_done);
  if (!built.ok) {
    if (built.error.kind === "already_complete") {
      return NextResponse.json(
        { error: "All hotels in the original job already finished; nothing to resume" },
        { status: 409 },
      );
    }
    return NextResponse.json({ error: built.error.kind }, { status: 500 });
  }

  const internalToken = process.env.JOBS_API_INTERNAL_TOKEN;
  if (!internalToken) {
    return NextResponse.json({ error: "JOBS_API_INTERNAL_TOKEN not configured" }, { status: 503 });
  }
  const jobsApi = process.env.JOBS_API ?? "http://jobs-api:8770";

  const upstream = await fetch(`${jobsApi}/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Auth": internalToken,
    },
    body: JSON.stringify(built.payload),
  });
  const text = await upstream.text();
  const json = (() => {
    try {
      return JSON.parse(text);
    } catch {
      return { error: text || "jobs-api returned non-JSON" };
    }
  })();
  // Echo back what we built so the client can show the user a clear
  // "resuming N hotels from $first" line without a second round-trip.
  if (upstream.ok) {
    // Persist the link so the UI hides the Resume button on subsequent
    // page loads. Best-effort: a write failure here doesn't undo the
    // already-spawned scrape; we just log and return success.
    if (typeof json.job_id === "string") {
      try {
        const updated = await markResumed(id, json.job_id);
        if (updated === 0) {
          // Either the parent vanished or someone raced us. The
          // spawned scrape is real and will run; the UI button just
          // won't disappear until the user reloads.
          console.warn(
            `[resume] markResumed(${id}, ${json.job_id}) updated 0 rows`,
          );
        }
      } catch (e) {
        // Hard failure (e.g. permission denied). Surface it in
        // `docker compose logs web` so the silent "button stays"
        // bug we hit earlier can't recur unnoticed.
        console.error("[resume] markResumed failed:", e);
      }
    }
    return NextResponse.json(
      {
        ...json,
        resumed_from_index: fetched.hotels_done,
        resumed_hotels: built.payload.hotels,
        resumed_dates: built.payload.dates,
      },
      { status: upstream.status },
    );
  }
  return NextResponse.json(json, { status: upstream.status });
}
