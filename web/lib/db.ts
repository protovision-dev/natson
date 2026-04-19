import postgres from "postgres";

declare global {
  // eslint-disable-next-line no-var
  var __pg: ReturnType<typeof postgres> | undefined;
}

function makeClient() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is required");
  return postgres(url, {
    max: 10,
    idle_timeout: 30,
    prepare: false,
  });
}

export function getSql(): ReturnType<typeof postgres> {
  if (!globalThis.__pg) {
    globalThis.__pg = makeClient();
  }
  return globalThis.__pg;
}

// Tagged-template proxy: `sql\`SELECT …\`` lazily resolves the underlying
// client on first call. Avoids module-load-time env validation that breaks
// Next.js's build-time route-metadata collection step.
export const sql = ((strings: TemplateStringsArray, ...values: unknown[]) =>
  // postgres.js client is itself callable as a tagged template.
  (getSql() as unknown as (s: TemplateStringsArray, ...v: unknown[]) => unknown)(
    strings,
    ...values,
  )) as unknown as ReturnType<typeof postgres>;
