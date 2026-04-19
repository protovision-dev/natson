import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { fetchActiveJobs, fetchRecentJobs } from "@/lib/jobs";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const url = new URL(req.url);
  const state = url.searchParams.get("state") ?? "all";

  if (state === "active") {
    return NextResponse.json({ active: await fetchActiveJobs() });
  }
  if (state === "recent") {
    return NextResponse.json({ recent: await fetchRecentJobs(50) });
  }
  const [active, recent] = await Promise.all([fetchActiveJobs(), fetchRecentJobs(50)]);
  return NextResponse.json({ active, recent });
}
