import { describe, expect, it, vi, beforeAll, afterAll } from "vitest";
import { render } from "@testing-library/react";
import { RateGrid } from "@/components/RateGrid";
import type { GridResponse } from "@/lib/queries";

// Pin "today" for deterministic orange-pill assertions. The grid uses
// America/New_York; clamping the system clock to mid-day UTC keeps the
// ET date stable.
beforeAll(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-04-19T12:00:00Z"));
});
afterAll(() => {
  vi.useRealTimers();
});

const grid: GridResponse = {
  rows: [
    {
      stay_date: "2026-04-18",
      market_demand_pct: 50,
      cells: [cell("100", "Subject", true, 99), cell("200", "Comp A", false, 110)],
    },
    {
      stay_date: "2026-04-19",
      market_demand_pct: 65,
      cells: [cell("100", "Subject", true, 105), cell("200", "Comp A", false, 120)],
    },
  ],
  competitors: [
    { id: "100", name: "Subject", is_own: true },
    { id: "200", name: "Comp A", is_own: false },
  ],
  last_observation_ts: "2026-04-19T10:00:00Z",
  last_extract_datetime: "2026-04-19T08:00:00Z",
};

function cell(
  id: string,
  name: string,
  is_own: boolean,
  rate: number,
): GridResponse["rows"][0]["cells"][0] {
  return {
    competitor_hotelinfo_id: id,
    competitor_name: name,
    is_own,
    rate_value: rate,
    shop_value: rate * 7,
    all_in_price: rate * 7.7,
    is_available: true,
    message: "",
    observation_ts: "2026-04-19T10:00:00Z",
    extract_datetime: "2026-04-19T08:00:00Z",
  };
}

describe("<RateGrid />", () => {
  it("places the subject column first in the header", () => {
    const { container } = render(<RateGrid data={grid} />);
    const headers = [...container.querySelectorAll("thead th")].map((th) => th.textContent?.trim());
    // Date, Market demand, Subject (own), Comp A
    expect(headers[0]).toMatch(/Date/);
    expect(headers[1]).toMatch(/Market/);
    expect(headers[2]).toBe("Subject");
    expect(headers[3]).toBe("Comp A");
  });

  it("renders empty state when no rows", () => {
    const { getByText } = render(<RateGrid data={{ ...grid, rows: [], competitors: [] }} />);
    expect(getByText(/No rate observations/)).toBeInTheDocument();
  });

  it("orange-tints today's date cell only", () => {
    const { container } = render(<RateGrid data={grid} />);
    const dateCells = container.querySelectorAll("tbody td:first-child");
    // 2026-04-18 row → no orange; 2026-04-19 row → orange.
    expect(dateCells[0].className).not.toMatch(/bg-orange-400/);
    expect(dateCells[1].className).toMatch(/bg-orange-400/);
  });
});
