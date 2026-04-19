import { getAuthPool } from "./auth";

export type AllowedDomain = {
  domain: string;
  added_by: string;
  added_at: string;
};

const DOMAIN_RE =
  /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

export function normalizeDomain(input: string): string | null {
  const trimmed = input.trim().toLowerCase().replace(/^@/, "");
  return DOMAIN_RE.test(trimmed) ? trimmed : null;
}

export async function listAllowedDomains(): Promise<AllowedDomain[]> {
  const r = await getAuthPool().query<AllowedDomain>(
    "SELECT domain, added_by, added_at::text FROM allowed_domains ORDER BY domain ASC",
  );
  return r.rows;
}

export async function addAllowedDomain(domain: string, addedBy: string): Promise<void> {
  await getAuthPool().query(
    "INSERT INTO allowed_domains (domain, added_by) VALUES ($1, $2) ON CONFLICT DO NOTHING",
    [domain, addedBy],
  );
}

export async function removeAllowedDomain(domain: string): Promise<boolean> {
  const r = await getAuthPool().query("DELETE FROM allowed_domains WHERE domain = $1", [
    domain.toLowerCase(),
  ]);
  return (r.rowCount ?? 0) > 0;
}
