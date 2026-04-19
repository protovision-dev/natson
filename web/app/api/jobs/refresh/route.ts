import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { subjectCodesToSubscriptionIds } from "@/lib/jobs";
import { z } from "zod";

export const dynamic = "force-dynamic";

const Body = z.object({
  subjects: z.array(z.string().min(1)).min(1),
  // YYYY-MM | YYYY-MM-DD | rolling:N | YYYY-MM-DD:YYYY-MM-DD
  dates: z.string().min(4),
  ota: z.enum(["bookingdotcom", "branddotcom"]).default("bookingdotcom"),
  los: z.number().int().positive().max(90).optional(),
  persons: z.number().int().positive().max(10).optional(),
  refresh: z.boolean().default(true),
});

export async function POST(req: Request) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const jobsApi = process.env.JOBS_API ?? "http://jobs-api:8770";

  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    const msg = e instanceof Error ? e.message : "invalid body";
    return NextResponse.json({ error: msg }, { status: 400 });
  }

  const hotels = await subjectCodesToSubscriptionIds(body.subjects);
  if (hotels.length === 0) {
    return NextResponse.json(
      { error: "No subscription IDs found for the given subject codes" },
      { status: 400 },
    );
  }

  const internalToken = process.env.JOBS_API_INTERNAL_TOKEN;
  if (!internalToken) {
    return NextResponse.json(
      { error: "JOBS_API_INTERNAL_TOKEN not configured" },
      { status: 503 },
    );
  }

  const upstream = await fetch(`${jobsApi}/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Auth": internalToken,
    },
    body: JSON.stringify({
      hotels,
      dates: body.dates,
      ota: body.ota,
      los: body.los,
      persons: body.persons,
      refresh: body.refresh,
    }),
  });

  const text = await upstream.text();
  const json = (() => {
    try {
      return JSON.parse(text);
    } catch {
      return { error: text || "jobs-api returned non-JSON" };
    }
  })();

  return NextResponse.json(json, { status: upstream.status });
}
