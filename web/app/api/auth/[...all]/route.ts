import { auth } from "@/lib/auth";
import { toNextJsHandler } from "better-auth/next-js";

export const dynamic = "force-dynamic";

// Defer handler resolution until first request so build-time route-metadata
// collection doesn't trip the env-var check inside lib/auth.
let cached: ReturnType<typeof toNextJsHandler> | undefined;
function handlers() {
  if (!cached) cached = toNextJsHandler(auth.handler);
  return cached;
}

export async function GET(req: Request) {
  return handlers().GET(req);
}

export async function POST(req: Request) {
  return handlers().POST(req);
}
