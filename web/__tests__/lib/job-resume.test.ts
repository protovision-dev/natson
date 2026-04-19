import { describe, expect, it } from "vitest";
import { buildResumePayload, type JobSpec } from "@/lib/job-resume";

const baseSpec: JobSpec = {
  hotels: ["100", "200", "300", "400", "500", "600", "700", "800", "900", "1000"],
  ota: "bookingdotcom",
  los: 7,
  persons: 2,
  do_refresh: true,
  checkin_dates: ["2026-04-01", "2026-04-02", "2026-04-15", "2026-04-30"],
  raw_dates_expr: "rolling:0",
};

describe("buildResumePayload", () => {
  it("re-scrapes from hotels_done forward (covers in-progress hotel)", () => {
    const r = buildResumePayload(baseSpec, 5);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.payload.hotels).toEqual(["600", "700", "800", "900", "1000"]);
    // 5 done, original was 10 → 5 remaining starting at the 6th.
    expect(r.payload.hotels.length).toBe(5);
  });

  it("preserves OTA, LOS, persons, refresh from the original spec", () => {
    const r = buildResumePayload({ ...baseSpec, ota: "branddotcom", los: 1, persons: 4 }, 3);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.payload.ota).toBe("branddotcom");
    expect(r.payload.los).toBe(1);
    expect(r.payload.persons).toBe(4);
    expect(r.payload.refresh).toBe(true);
  });

  it("pins to the original date range (not the original raw expression)", () => {
    // raw_dates_expr is rolling:0 which would re-evaluate to today's
    // month; resume must use the explicit checkin_dates window so the
    // re-run hits the same calendar days.
    const r = buildResumePayload(baseSpec, 5);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.payload.dates).toBe("2026-04-01:2026-04-30");
  });

  it("handles a fresh failure at hotel 1 (hotels_done=0)", () => {
    const r = buildResumePayload(baseSpec, 0);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.payload.hotels).toEqual(baseSpec.hotels);
  });

  it("returns 'already_complete' when hotels_done >= hotels.length", () => {
    const r = buildResumePayload(baseSpec, 10);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.error.kind).toBe("already_complete");
  });

  it("clamps an out-of-range hotels_done to nothing-to-do", () => {
    const r = buildResumePayload(baseSpec, 99);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.error.kind).toBe("already_complete");
  });

  it("returns bad_spec when hotels list is empty", () => {
    const r = buildResumePayload({ ...baseSpec, hotels: [] }, 0);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.error.kind).toBe("bad_spec");
  });

  it("returns bad_spec when checkin_dates is empty", () => {
    const r = buildResumePayload({ ...baseSpec, checkin_dates: [] }, 5);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.error.kind).toBe("bad_spec");
  });
});
