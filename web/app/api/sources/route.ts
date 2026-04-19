import { NextResponse } from "next/server";
import { fetchSources } from "@/lib/queries";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";

export const dynamic = "force-dynamic";

export async function GET() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const rows = await fetchSources();
  return NextResponse.json({ sources: rows });
}
