import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fmtMoney, fmtDateShort, relativeTime } from "@/lib/utils";

describe("fmtMoney", () => {
  it("renders dollars with the $ prefix and rounded value", () => {
    expect(fmtMoney(71.49)).toBe("$ 71");
    expect(fmtMoney(71.5)).toBe("$ 72");
    expect(fmtMoney(0)).toBe("$ 0");
  });

  it("returns em-dash for null/undefined", () => {
    expect(fmtMoney(null)).toBe("—");
    expect(fmtMoney(undefined)).toBe("—");
  });
});

describe("fmtDateShort", () => {
  it("formats an ISO date as 'Day, MM/DD'", () => {
    // 2026-04-19 was a Sunday.
    expect(fmtDateShort("2026-04-19")).toMatch(/^Sun, 04\/19$/);
  });
});

describe("relativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-19T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns em-dash for null/undefined", () => {
    expect(relativeTime(null)).toBe("—");
    expect(relativeTime(undefined)).toBe("—");
  });

  it("buckets sub-minute as 'just now'", () => {
    expect(relativeTime("2026-04-19T11:59:45Z")).toBe("just now");
  });

  it("uses minutes / hours / days at the right thresholds", () => {
    expect(relativeTime("2026-04-19T11:30:00Z")).toBe("30 min ago");
    expect(relativeTime("2026-04-19T09:00:00Z")).toBe("3 hrs ago");
    expect(relativeTime("2026-04-15T12:00:00Z")).toBe("4 days ago");
  });
});
