import { NextResponse } from "next/server";
import { headers } from "next/headers";
import { z } from "zod";

import { auth } from "@/lib/auth";
import { isAdmin } from "@/lib/admin";
import { addAllowedDomain, listAllowedDomains, normalizeDomain } from "@/lib/allowed-domains";

export const dynamic = "force-dynamic";

const PostBody = z.object({
  domain: z.string().min(1).max(253),
});

export async function GET() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (!isAdmin(session.user.email)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  return NextResponse.json({ domains: await listAllowedDomains() });
}

export async function POST(req: Request) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (!isAdmin(session.user.email)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  let body: z.infer<typeof PostBody>;
  try {
    body = PostBody.parse(await req.json());
  } catch (e) {
    const msg = e instanceof Error ? e.message : "invalid body";
    return NextResponse.json({ error: msg }, { status: 400 });
  }

  const normalized = normalizeDomain(body.domain);
  if (!normalized) {
    return NextResponse.json({ error: `Invalid domain: ${body.domain}` }, { status: 400 });
  }

  await addAllowedDomain(normalized, session.user.email);
  return NextResponse.json({ domain: normalized }, { status: 201 });
}
