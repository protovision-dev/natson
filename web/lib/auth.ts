import { betterAuth, type BetterAuthOptions } from "better-auth";
import { createAuthMiddleware, APIError } from "better-auth/api";
import { Pool } from "pg";

import { sendEmail } from "./email";

declare global {
  // eslint-disable-next-line no-var
  var __auth: ReturnType<typeof betterAuth> | undefined;
}

// Server-side complexity check. Length (≥12) is enforced by better-auth
// directly via minPasswordLength; this hook adds the character-class
// requirement on top so we reject "aaaaaaaaaaaa" but accept "Tr0ub4dor".
const PASSWORD_COMPLEXITY = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/;
const PASSWORD_COMPLEXITY_MSG = "Password must include lowercase, uppercase, and a digit";

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

  const isProd = process.env.NODE_ENV === "production";
  const baseURL = process.env.BETTER_AUTH_URL ?? "http://localhost:3020";

  const opts: BetterAuthOptions = {
    database: pool,
    baseURL,
    secret: process.env.BETTER_AUTH_SECRET,
    emailAndPassword: {
      enabled: true,
      requireEmailVerification: true,
      autoSignIn: false,
      minPasswordLength: 12,
      sendResetPassword: async ({ user, url: resetUrl }) => {
        await sendEmail({
          to: user.email,
          subject: "Reset your Natson password",
          text: `Click to reset your password:\n\n${resetUrl}\n\nIf you didn't request this, ignore this email.`,
        });
      },
    },
    emailVerification: {
      sendOnSignUp: true,
      autoSignInAfterVerification: true,
      sendVerificationEmail: async ({ user, url: verifyUrl }) => {
        await sendEmail({
          to: user.email,
          subject: "Verify your Natson email",
          text: `Click to verify your email and finish signing up:\n\n${verifyUrl}\n\nThis link expires in 24 hours.`,
        });
      },
    },
    session: {
      expiresIn: 60 * 60 * 24 * 7, // 7 days (kept per user request)
      updateAge: 60 * 60 * 24,
    },
    rateLimit: {
      enabled: true,
      window: 60,
      max: 100,
      // Tighter caps on auth endpoints — defeats credential stuffing
      // and signup spam without throttling normal app traffic.
      customRules: {
        "/sign-in/email": { window: 600, max: 5 },
        "/sign-up/email": { window: 600, max: 5 },
        "/forget-password": { window: 3600, max: 5 },
      },
    },
    advanced: {
      useSecureCookies: isProd,
      defaultCookieAttributes: {
        httpOnly: true,
        sameSite: "lax",
        secure: isProd,
      },
    },
    hooks: {
      // Server-side gate so a direct API call can't bypass the
      // client-side complexity check.
      before: createAuthMiddleware(async (ctx) => {
        if (
          ctx.path === "/sign-up/email" ||
          ctx.path === "/reset-password" ||
          ctx.path === "/change-password"
        ) {
          const password =
            (ctx.body as { password?: string; newPassword?: string } | undefined)?.password ??
            (ctx.body as { newPassword?: string } | undefined)?.newPassword;
          if (password && !PASSWORD_COMPLEXITY.test(password)) {
            throw new APIError("BAD_REQUEST", { message: PASSWORD_COMPLEXITY_MSG });
          }
        }
      }),
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
