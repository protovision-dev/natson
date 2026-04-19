import { NextResponse } from "next/server";
import { fetchGrid } from "@/lib/queries";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const url = new URL(req.url);
  const subject = url.searchParams.get("subject");
  const source = url.searchParams.get("source") ?? "booking";
  const los = Number(url.searchParams.get("los") ?? "7");
  const persons = Number(url.searchParams.get("persons") ?? "2");
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");

  if (!subject || !from || !to) {
    return NextResponse.json({ error: "subject, from, to are required" }, { status: 400 });
  }

  try {
    const data = await fetchGrid({ subject, source, los, persons, from, to });
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
