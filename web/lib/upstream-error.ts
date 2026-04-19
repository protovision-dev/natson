/**
 * Convert jobs-api / FastAPI / Pydantic error response shapes into a
 * single string the React client can render via `data.error`.
 *
 * jobs-api uses HTTPException(detail=…), so its bodies look like
 *   {"detail": "Max parallel jobs reached (2). Try again shortly."}
 *
 * Pydantic validation rejections look like
 *   {"detail": [{"loc": ["body","los"], "msg": "...", "type": "..."}]}
 *
 * Our React clients (AdminScrapeForm, JobResumeButton) read
 * `data.error`. Without normalization they'd display "Failed (429)"
 * and the user would have to crack open devtools to see why.
 */
export function humanizeUpstreamError(
  status: number,
  body: Record<string, unknown>,
): string {
  if (typeof body.error === "string" && body.error.length > 0) return body.error;

  const detail = body.detail;
  if (typeof detail === "string" && detail.length > 0) {
    if (status === 429) return `All scrape slots are busy — ${detail}`;
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    // Pydantic's validation array.
    return detail
      .map((d) => {
        const e = d as { loc?: unknown[]; msg?: string };
        const where =
          Array.isArray(e.loc) && e.loc.length > 0 ? String(e.loc[e.loc.length - 1]) : "input";
        return `${where}: ${e.msg ?? "invalid"}`;
      })
      .join("; ");
  }

  if (status === 429) return "All scrape slots are busy. Try again when one finishes.";
  if (status === 401) return "Sign-in required";
  if (status === 403) return "Not authorized";
  if (status === 404) return "Not found";
  if (status === 503) return "Jobs sidecar is unavailable";
  return `Request failed (${status})`;
}
