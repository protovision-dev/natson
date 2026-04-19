import { describe, expect, it, vi, beforeEach } from "vitest";

// Mock the postgres client BEFORE importing queries.ts so the lazy sql()
// resolves to our stub instead of trying to open a real connection.
const mockTagged = vi.fn();
vi.mock("@/lib/db", () => ({
  sql: (strings: TemplateStringsArray, ...values: unknown[]) => mockTagged(strings, ...values),
  getSql: () => () => mockTagged,
}));

import { fetchGrid } from "@/lib/queries";

describe("fetchGrid", () => {
  beforeEach(() => {
    mockTagged.mockReset();
  });

  it("pivots flat rows into per-date rows + competitor list (own first)", async () => {
    mockTagged.mockResolvedValueOnce([
      {
        stay_date: "2026-04-19",
        market_demand_pct: 65,
        competitor_hotelinfo_id: "100",
        competitor_name: "Subject Hotel",
        is_own: true,
        rate_value: 99,
        shop_value: 693,
        all_in_price: 770,
        is_available: true,
        message: "",
        observation_ts: "2026-04-19T10:00:00Z",
        extract_datetime: "2026-04-19T08:00:00Z",
      },
      {
        stay_date: "2026-04-19",
        market_demand_pct: 65,
        competitor_hotelinfo_id: "200",
        competitor_name: "Bravo Comp",
        is_own: false,
        rate_value: 110,
        shop_value: 770,
        all_in_price: 850,
        is_available: true,
        message: "",
        observation_ts: "2026-04-19T10:00:00Z",
        extract_datetime: "2026-04-19T07:00:00Z",
      },
      {
        stay_date: "2026-04-19",
        market_demand_pct: 65,
        competitor_hotelinfo_id: "300",
        competitor_name: "Alpha Comp",
        is_own: false,
        rate_value: null,
        shop_value: null,
        all_in_price: null,
        is_available: false,
        message: "rates.soldout",
        observation_ts: "2026-04-19T11:00:00Z",
        extract_datetime: null,
      },
      {
        stay_date: "2026-04-20",
        market_demand_pct: 70,
        competitor_hotelinfo_id: "100",
        competitor_name: "Subject Hotel",
        is_own: true,
        rate_value: 105,
        shop_value: 735,
        all_in_price: 815,
        is_available: true,
        message: "",
        observation_ts: "2026-04-19T11:00:00Z",
        extract_datetime: "2026-04-19T08:30:00Z",
      },
    ]);

    const result = await fetchGrid({
      subject: "X",
      source: "booking",
      los: 7,
      from: "2026-04-19",
      to: "2026-04-20",
    });

    // Two distinct dates, sorted ascending.
    expect(result.rows).toHaveLength(2);
    expect(result.rows[0].stay_date).toBe("2026-04-19");
    expect(result.rows[1].stay_date).toBe("2026-04-20");

    // First row gathers all 3 cells; second only has the own cell.
    expect(result.rows[0].cells).toHaveLength(3);
    expect(result.rows[1].cells).toHaveLength(1);

    // Competitors: own first, then alphabetical.
    expect(result.competitors.map((c) => c.name)).toEqual([
      "Subject Hotel",
      "Alpha Comp",
      "Bravo Comp",
    ]);
    expect(result.competitors[0].is_own).toBe(true);

    // Last-updated picks the max across all rows, including the
    // sold-out row's later observation_ts.
    expect(result.last_observation_ts).toBe("2026-04-19T11:00:00Z");
    expect(result.last_extract_datetime).toBe("2026-04-19T08:30:00Z");
  });

  it("returns empty shape when the query returns no rows", async () => {
    mockTagged.mockResolvedValueOnce([]);
    const result = await fetchGrid({
      subject: "X",
      source: "booking",
      los: 7,
      from: "2026-04-19",
      to: "2026-04-20",
    });
    expect(result.rows).toEqual([]);
    expect(result.competitors).toEqual([]);
    expect(result.last_observation_ts).toBeNull();
    expect(result.last_extract_datetime).toBeNull();
  });
});
