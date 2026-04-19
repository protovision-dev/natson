import { betterAuth, type BetterAuthOptions } from "better-auth";
import { Pool } from "pg";

declare global {
  // eslint-disable-next-line no-var
  var __auth: ReturnType<typeof betterAuth> | undefined;
}

function makeAuth() {
  const url = process.env.AUTH_DATABASE_URL;
  if (!url) throw new Error("AUTH_DATABASE_URL is required");

  // `options` sets PGOPTIONS for every connection in the pool, pinning
  // search_path so better-auth's unqualified `user`/`session`/`account`/
  // `verification` table references resolve inside the `auth` schema.
  const pool = new Pool({
    connectionString: url,
    max: 5,
    idleTimeoutMillis: 30_000,
    options: "-c search_path=auth,public",
  });

  const opts: BetterAuthOptions = {
    database: pool,
    baseURL: process.env.BETTER_AUTH_URL ?? "http://localhost:3000",
    secret: process.env.BETTER_AUTH_SECRET,
    emailAndPassword: {
      enabled: true,
      requireEmailVerification: false,
      autoSignIn: true,
      minPasswordLength: 8,
    },
    session: {
      expiresIn: 60 * 60 * 24 * 7,
      updateAge: 60 * 60 * 24,
    },
  };

  return betterAuth(opts);
}

// Lazy proxy so module load doesn't require env vars to be set
// (Next.js's build-time route-metadata pass evaluates this module).
export const auth = new Proxy({} as ReturnType<typeof betterAuth>, {
  get(_t, prop) {
    if (!globalThis.__auth) globalThis.__auth = makeAuth();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (globalThis.__auth as any)[prop];
  },
});
