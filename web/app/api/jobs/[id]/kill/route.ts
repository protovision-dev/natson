import { NextResponse } from "next/server";
import { headers } from "next/headers";

import { auth } from "@/lib/auth";
import { isAdmin } from "@/lib/admin";
import { markJobFailed } from "@/lib/jobs";

export const dynamic = "force-dynamic";

export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (!isAdmin(session.user.email)) {
    return NextResponse.json({ error: "Only admins can kill jobs" }, { status: 403 });
  }

  const { id } = await ctx.params;
  const reason = `killed by ${session.user.email} via UI`;
  const updated = await markJobFailed(id, reason);

  if (updated === 0) {
    return NextResponse.json(
      { error: "Job not found or already in a terminal state" },
      { status: 409 },
    );
  }
  return NextResponse.json({ ok: true, job_id: id, marked: "failed" });
}
