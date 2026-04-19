/**
 * Admin identity helpers. The admin allow-list lives in $ADMIN_EMAILS
 * (comma-separated, case-insensitive). We resolve it on every check
 * rather than caching at module load so a redeploy with a new env
 * value takes effect on the next request, no rebuild required.
 */

function adminEmails(): Set<string> {
  const raw = process.env.ADMIN_EMAILS ?? "";
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function isAdmin(email: string | null | undefined): boolean {
  if (!email) return false;
  return adminEmails().has(email.toLowerCase());
}

/** Lower-case domain part of an email, or null if malformed. */
export function emailDomain(email: string): string | null {
  const at = email.lastIndexOf("@");
  if (at < 1 || at === email.length - 1) return null;
  return email.slice(at + 1).toLowerCase();
}
