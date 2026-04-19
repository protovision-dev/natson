import { type GridResponse } from "@/lib/queries";
import { RateCell } from "./RateCell";
import { MarketDemandCell } from "./MarketDemandCell";
import { fmtDateShort } from "@/lib/utils";

// Frozen-left column widths. Subject column carries a 2px border on its
// right edge to mark the freeze line; competitors scroll horizontally.
const W_DATE = 96;
const W_DEMAND = 132;
const W_SUBJECT = 150;
const W_COMP = 132;

const LEFT_DATE = 0;
const LEFT_DEMAND = W_DATE;
const LEFT_SUBJECT = W_DATE + W_DEMAND;

// Use America/New_York since the portfolio is US-based; date pill should
// match what the operator considers "today" in their working timezone.
function todayInPortfolioTz(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
  }).format(new Date());
}

export function RateGrid({ data }: { data: GridResponse }) {
  if (data.rows.length === 0) {
    return (
      <div className="rounded border border-line bg-white p-8 text-center text-sm text-subtle">
        No rate observations for this combination yet.
      </div>
    );
  }

  const own = data.competitors.find((c) => c.is_own) ?? null;
  const others = data.competitors.filter((c) => !c.is_own);
  const today = todayInPortfolioTz();

  return (
    <div className="h-full overflow-auto rounded border border-line bg-white">
      <table className="border-collapse text-sm">
        <thead className="sticky top-0 z-20 bg-white">
          <tr className="border-b border-line">
            <th
              className="sticky z-30 bg-white px-2 py-1.5 text-left text-[11px] font-medium leading-tight"
              style={{ left: LEFT_DATE, width: W_DATE, minWidth: W_DATE }}
            >
              Date
            </th>
            <th
              className="sticky z-30 bg-white px-2 py-1.5 text-left text-[11px] font-medium leading-tight"
              style={{ left: LEFT_DEMAND, width: W_DEMAND, minWidth: W_DEMAND }}
            >
              Market demand
            </th>
            <th
              className="sticky z-30 border-r-2 border-r-zinc-300 bg-ownRow px-2 py-1.5 text-left text-[11px] font-medium leading-tight"
              style={{ left: LEFT_SUBJECT, width: W_SUBJECT, minWidth: W_SUBJECT }}
              title={own?.name ?? "Subject property"}
            >
              <div className="line-clamp-2 break-words">
                {own?.name ?? "Subject"}
              </div>
            </th>
            {others.map((c) => (
              <th
                key={c.id}
                className="px-2 py-1.5 text-left align-bottom text-[11px] font-medium leading-tight"
                style={{ width: W_COMP, minWidth: W_COMP, maxWidth: W_COMP }}
                title={c.name}
              >
                <div className="line-clamp-2 break-words">{c.name}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => {
            const ownCell = own
              ? r.cells.find((x) => x.competitor_hotelinfo_id === own.id) ?? null
              : null;
            const isToday = r.stay_date === today;

            return (
              <tr
                key={r.stay_date}
                className="group border-b border-line/60"
              >
                <td
                  className={
                    "sticky z-10 px-2 py-1.5 font-medium " +
                    (isToday
                      ? "bg-orange-400 text-white group-hover:bg-orange-500"
                      : "bg-white group-hover:bg-zinc-200")
                  }
                  style={{ left: LEFT_DATE, width: W_DATE, minWidth: W_DATE }}
                >
                  {fmtDateShort(r.stay_date)}
                </td>
                <td
                  className="sticky z-10 bg-white px-2 py-1.5 group-hover:bg-zinc-200"
                  style={{ left: LEFT_DEMAND, width: W_DEMAND, minWidth: W_DEMAND }}
                >
                  <MarketDemandCell pct={r.market_demand_pct} />
                </td>
                <td
                  className="sticky z-10 border-r-2 border-r-zinc-300 bg-ownRow/60 px-2 py-1.5 text-right group-hover:bg-zinc-200"
                  style={{ left: LEFT_SUBJECT, width: W_SUBJECT, minWidth: W_SUBJECT }}
                >
                  <RateCell cell={ownCell} />
                </td>
                {others.map((c) => {
                  const cell = r.cells.find((x) => x.competitor_hotelinfo_id === c.id);
                  return (
                    <td
                      key={c.id}
                      className="px-2 py-1.5 text-right group-hover:bg-zinc-200"
                      style={{ width: W_COMP, minWidth: W_COMP, maxWidth: W_COMP }}
                    >
                      <RateCell cell={cell ?? null} />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
