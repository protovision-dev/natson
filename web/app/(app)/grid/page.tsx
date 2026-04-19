import { fetchAvailableMonths, fetchGrid, fetchSources, fetchSubjects } from "@/lib/queries";
import { RateGrid } from "@/components/RateGrid";
import { LastUpdatedCard } from "@/components/LastUpdatedCard";
import { FilterBar } from "@/components/FilterBar";

export const dynamic = "force-dynamic";

type Search = Record<string, string | string[] | undefined>;

function pickFirst(s: string | string[] | undefined): string | undefined {
  return Array.isArray(s) ? s[0] : s;
}

function currentMonthInPortfolioTz(): string {
  // Match the today-pill in RateGrid: portfolio is US-based, anchor to ET.
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
  });
  const parts = fmt.formatToParts(new Date());
  const y = parts.find((p) => p.type === "year")!.value;
  const m = parts.find((p) => p.type === "month")!.value;
  return `${y}-${m}`;
}

function monthBounds(ym: string): { from: string; to: string } {
  const [y, m] = ym.split("-").map(Number);
  // Last day of the same month: day=0 of the next month.
  const last = new Date(Date.UTC(y, m, 0));
  const lastDay = String(last.getUTCDate()).padStart(2, "0");
  return { from: `${ym}-01`, to: `${ym}-${lastDay}` };
}

export default async function GridPage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const [subjects, sources] = await Promise.all([fetchSubjects(), fetchSources()]);

  const subject = pickFirst(sp.subject) ?? subjects[0]?.subject_code;
  const source = pickFirst(sp.source) ?? sources[0]?.source_code ?? "booking";
  const los = Number(pickFirst(sp.los) ?? "7");
  const persons = Number(pickFirst(sp.persons) ?? "2");

  if (!subject) {
    return (
      <div className="p-8 text-sm text-subtle">
        No subject hotels found. Run a scrape first to populate <code>subject_hotels</code>.
      </div>
    );
  }

  const months = await fetchAvailableMonths(subject, source);
  const requestedMonth = pickFirst(sp.month);
  const currentMonth = currentMonthInPortfolioTz();

  // Pick a month: explicit URL param if it exists in the available list,
  // else current month if available, else the first available month.
  const month =
    (requestedMonth && months.includes(requestedMonth) && requestedMonth) ||
    (months.includes(currentMonth) && currentMonth) ||
    months[0] ||
    currentMonth;

  // From = first of selected month. To = last day of the LAST month with
  // data, so picking an earlier month widens the window through the same
  // far end. Falls back to the selected month's last day if no data.
  const { from } = monthBounds(month);
  const farMonth = months[months.length - 1] ?? month;
  const { to } = monthBounds(farMonth);

  const data = await fetchGrid({ subject, source, los, persons, from, to });

  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden p-4">
      <div className="flex shrink-0 flex-wrap items-center gap-3">
        <FilterBar
          subjects={subjects}
          sources={sources}
          months={months}
          current={{ subject, source, los, persons, month }}
        />
        <span className="ml-auto" />
        <LastUpdatedCard
          observation={data.last_observation_ts}
          extract={data.last_extract_datetime}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        <RateGrid data={data} />
      </div>
    </div>
  );
}
