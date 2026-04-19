/**
 * Email transport for better-auth verification + (future) password
 * resets. Two backends:
 *   - Production: Resend (set RESEND_API_KEY).
 *   - Dev: log to stdout. Lets you click the verification URL out of
 *     `docker compose logs web` without configuring SMTP.
 *
 * The function is a no-op-with-log if RESEND_API_KEY is missing, so a
 * misconfigured prod deploy fails loudly (signups stuck on "verify
 * your email") rather than silently bypassing verification.
 */

const FROM = process.env.RESEND_FROM ?? "Natson <noreply@natson.local>";

type EmailArgs = {
  to: string;
  subject: string;
  text: string;
  html?: string;
};

export async function sendEmail({ to, subject, text, html }: EmailArgs): Promise<void> {
  const apiKey = process.env.RESEND_API_KEY;

  if (!apiKey) {
    console.log(
      [
        "[email] RESEND_API_KEY not set — printing to stdout (dev mode):",
        `  To:      ${to}`,
        `  From:    ${FROM}`,
        `  Subject: ${subject}`,
        "  Body:",
        text
          .split("\n")
          .map((l) => `    ${l}`)
          .join("\n"),
      ].join("\n"),
    );
    return;
  }

  // Use Resend's HTTP API directly — no extra dependency to maintain
  // since we only need a single endpoint.
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: FROM,
      to,
      subject,
      text,
      html: html ?? `<pre style="font-family:system-ui,sans-serif">${escapeHtml(text)}</pre>`,
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Resend send failed (${res.status}): ${body}`);
  }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
