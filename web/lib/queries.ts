import { sql } from "./db";

export type RateCell = {
  competitor_hotelinfo_id: string;
  competitor_name: string;
  is_own: boolean;
  rate_value: number | null;
  shop_value: number | null;
  all_in_price: number | null;
  is_available: boolean;
  message: string | null;
  observation_ts: string | null;
  extract_datetime: string | null;
};

export type GridRow = {
  stay_date: string;
  market_demand_pct: number | null;
  cells: RateCell[];
};

export type GridResponse = {
  rows: GridRow[];
  competitors: { id: string; name: string; is_own: boolean }[];
  last_observation_ts: string | null;
  last_extract_datetime: string | null;
};

export async function fetchGrid(params: {
  subject: string;
  source: string;
  los: number;
  persons?: number;
  from: string;
  to: string;
}): Promise<GridResponse> {
  const { subject, source, los, persons = 2, from, to } = params;
  const rows = await sql<{
    stay_date: string;
    market_demand_pct: number | null;
    competitor_hotelinfo_id: string;
    competitor_name: string;
    is_own: boolean;
    rate_value: number | null;
    shop_value: number | null;
    all_in_price: number | null;
    is_available: boolean;
    message: string | null;
    observation_ts: string | null;
    extract_datetime: string | null;
  }[]>`
    SELECT
      stay_date::text,
      market_demand_pct,
      competitor_hotelinfo_id,
      competitor_name,
      is_own,
      rate_value,
      shop_value,
      all_in_price,
      is_available,
      message,
      observation_ts::text,
      extract_datetime::text
    FROM v_rate_grid_latest
    WHERE subject_code = ${subject}
      AND source_code  = ${source}
      AND los          = ${los}
      AND persons      = ${persons}
      AND stay_date BETWEEN ${from}::date AND ${to}::date
    ORDER BY stay_date ASC, is_own DESC, competitor_name ASC
  `;

  const compMap = new Map<string, { id: string; name: string; is_own: boolean }>();
  const dateMap = new Map<string, GridRow>();
  let maxObs: string | null = null;
  let maxExt: string | null = null;

  for (const r of rows) {
    if (!compMap.has(r.competitor_hotelinfo_id)) {
      compMap.set(r.competitor_hotelinfo_id, {
        id: r.competitor_hotelinfo_id,
        name: r.competitor_name,
        is_own: r.is_own,
      });
    }
    let row = dateMap.get(r.stay_date);
    if (!row) {
      row = { stay_date: r.stay_date, market_demand_pct: r.market_demand_pct, cells: [] };
      dateMap.set(r.stay_date, row);
    }
    row.cells.push({
      competitor_hotelinfo_id: r.competitor_hotelinfo_id,
      competitor_name: r.competitor_name,
      is_own: r.is_own,
      rate_value: r.rate_value == null ? null : Number(r.rate_value),
      shop_value: r.shop_value == null ? null : Number(r.shop_value),
      all_in_price: r.all_in_price == null ? null : Number(r.all_in_price),
      is_available: r.is_available,
      message: r.message,
      observation_ts: r.observation_ts,
      extract_datetime: r.extract_datetime,
    });
    if (r.observation_ts && (!maxObs || r.observation_ts > maxObs)) maxObs = r.observation_ts;
    if (r.extract_datetime && (!maxExt || r.extract_datetime > maxExt)) maxExt = r.extract_datetime;
  }

  // Order competitors: own first, then alphabetical.
  const competitors = [...compMap.values()].sort((a, b) => {
    if (a.is_own !== b.is_own) return a.is_own ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return {
    rows: [...dateMap.values()].sort((a, b) => a.stay_date.localeCompare(b.stay_date)),
    competitors,
    last_observation_ts: maxObs,
    last_extract_datetime: maxExt,
  };
}

export async function fetchSubjects() {
  return sql<{ subject_code: string; display_name: string }[]>`
    SELECT internal_code AS subject_code, display_name
    FROM subject_hotels
    ORDER BY display_name ASC
  `;
}

export async function fetchSources() {
  return sql<{ source_code: string }[]>`
    SELECT source_code FROM sources ORDER BY source_code
  `;
}

/**
 * Distinct YYYY-MM months that have rate observations for the given
 * subject + source. Drives the Month dropdown in FilterBar; selecting
 * a month sets the grid's `from` to the 1st of that month and `to` to
 * the last day of the latest month in this list.
 */
export async function fetchAvailableMonths(
  subject: string,
  source: string,
): Promise<string[]> {
  const rows = await sql<{ ym: string }[]>`
    SELECT DISTINCT to_char(stay_date, 'YYYY-MM') AS ym
    FROM v_rate_grid_latest
    WHERE subject_code = ${subject}
      AND source_code  = ${source}
    ORDER BY ym ASC
  `;
  return rows.map((r) => r.ym);
}
