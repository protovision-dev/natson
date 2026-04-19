import { fetchActiveJobs, fetchRecentJobs, type ActiveJob, type RecentJob } from "@/lib/jobs";
import { JobsAutoRefresh } from "./jobs-auto-refresh";
import { relativeTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
  const [active, recent] = await Promise.all([fetchActiveJobs(), fetchRecentJobs(50)]);

  return (
    <div className="flex flex-col gap-6 p-4">
      <JobsAutoRefresh />

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-subtle">
          Active scrapes ({active.length})
        </h2>
        {active.length === 0 ? (
          <div className="rounded border border-line bg-white p-4 text-sm text-subtle">
            No active scrapes. Use the Refresh rates button on the grid to start one.
          </div>
        ) : (
          <ActiveTable rows={active} />
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-subtle">
          Recent scrapes (last {recent.length})
        </h2>
        <RecentTable rows={recent} />
      </section>
    </div>
  );
}

function ActiveTable({ rows }: { rows: ActiveJob[] }) {
  return (
    <div className="overflow-auto rounded border border-line bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-line bg-zinc-50 text-left text-xs text-subtle">
          <tr>
            <Th>Job</Th>
            <Th>State</Th>
            <Th>OTA</Th>
            <Th>Range</Th>
            <Th>Progress</Th>
            <Th>Current</Th>
            <Th>Step</Th>
            <Th>Started</Th>
            <Th>Elapsed</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.job_id} className="border-b border-line/60">
              <Td mono>{r.job_id}</Td>
              <Td>
                <StateBadge state={r.state} />
              </Td>
              <Td>{r.ota ?? "—"}</Td>
              <Td>
                {r.checkin_from ? r.checkin_from.slice(0, 10) : "—"} →{" "}
                {r.checkin_to ? r.checkin_to.slice(0, 10) : "—"}
              </Td>
              <Td>
                {r.hotels_done}/{r.hotels_total}
                {r.hotels_failed > 0 ? ` (${r.hotels_failed} fail)` : ""}
              </Td>
              <Td>{r.current_hotel ?? "—"}</Td>
              <Td>{r.current_step ?? "—"}</Td>
              <Td>{relativeTime(r.started_at)}</Td>
              <Td>{r.running_seconds}s</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecentTable({ rows }: { rows: RecentJob[] }) {
  return (
    <div className="overflow-auto rounded border border-line bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-line bg-zinc-50 text-left text-xs text-subtle">
          <tr>
            <Th>Job</Th>
            <Th>State</Th>
            <Th>OTA</Th>
            <Th>Range</Th>
            <Th>Hotels</Th>
            <Th>Started</Th>
            <Th>Duration</Th>
            <Th>Exit</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.job_id} className="border-b border-line/60">
              <Td mono>{r.job_id}</Td>
              <Td>
                <StateBadge state={r.state} />
              </Td>
              <Td>{r.ota ?? "—"}</Td>
              <Td>
                {r.checkin_from ? r.checkin_from.slice(0, 10) : "—"} →{" "}
                {r.checkin_to ? r.checkin_to.slice(0, 10) : "—"}
              </Td>
              <Td>
                {r.hotels_done}/{r.hotels_total}
                {r.hotels_failed > 0 ? ` (${r.hotels_failed} fail)` : ""}
              </Td>
              <Td>{relativeTime(r.started_at)}</Td>
              <Td>{r.duration_seconds}s</Td>
              <Td>{r.exit_code ?? "—"}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium">{children}</th>;
}

function Td({ children, mono = false }: { children: React.ReactNode; mono?: boolean }) {
  return <td className={"px-3 py-2 align-top " + (mono ? "font-mono text-xs" : "")}>{children}</td>;
}

function StateBadge({ state }: { state: string }) {
  const cls =
    state === "completed"
      ? "bg-green-50 text-green-800 ring-green-200"
      : state === "failed"
        ? "bg-red-50 text-red-800 ring-red-200"
        : state === "running"
          ? "bg-blue-50 text-blue-800 ring-blue-200"
          : "bg-zinc-50 text-zinc-700 ring-zinc-200";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}>
      {state}
    </span>
  );
}
