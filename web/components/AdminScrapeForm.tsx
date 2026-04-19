"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";

type Subject = { subject_code: string; display_name: string };

type Phase = "idle" | "submitting" | "running" | "done" | "error";

const OTAS = [
  { value: "bookingdotcom", label: "Booking.com" },
  { value: "branddotcom", label: "Brand.com" },
] as const;

export function AdminScrapeForm({ subjects }: { subjects: Subject[] }) {
  const router = useRouter();
  const [ota, setOta] = useState<(typeof OTAS)[number]["value"]>("bookingdotcom");
  // "" → portfolio (all properties); otherwise a subject_code.
  const [subject, setSubject] = useState<string>("");
  const [los, setLos] = useState<1 | 7 | 28>(7);
  const [phase, setPhase] = useState<Phase>("idle");
  const [msg, setMsg] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);

  // Brand only carries 1 and 7 day rates; auto-shift LOS if it falls
  // out of bounds when the OTA changes.
  const losOptions: readonly (1 | 7 | 28)[] = useMemo(
    () => (ota === "branddotcom" ? [1, 7] : [1, 7, 28]),
    [ota],
  );
  useEffect(() => {
    if (!losOptions.includes(los)) {
      setLos(losOptions[losOptions.length - 1] ?? 7);
    }
  }, [los, losOptions]);

  async function trigger() {
    setPhase("submitting");
    setMsg("Triggering scrape…");
    try {
      const subjectCodes = subject ? [subject] : subjects.map((s) => s.subject_code);
      const res = await fetch("/api/jobs/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subjects: subjectCodes,
          // Default window for admin-triggered scrapes: current month
          // through the next 2 months. Tunable later if we need it.
          dates: "rolling:2",
          ota,
          los,
          persons: 2,
          refresh: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setPhase("error");
        setMsg(data.error ?? `Failed (${res.status})`);
        return;
      }
      setJobId(data.job_id);
      setPhase("running");
      setMsg(`Job ${data.job_id} running…`);
      void poll(data.job_id);
    } catch (e) {
      setPhase("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  async function poll(id: string) {
    const start = Date.now();
    const TIMEOUT_MS = 30 * 60 * 1000; // portfolio scrapes can take a while
    while (Date.now() - start < TIMEOUT_MS) {
      await new Promise((r) => setTimeout(r, 4000));
      try {
        const res = await fetch(`/api/jobs/${id}`);
        if (res.status === 404) {
          setMsg(`Waiting for ${id} to register…`);
          continue;
        }
        if (!res.ok) {
          setMsg(`Status check failed (${res.status})`);
          continue;
        }
        const job = await res.json();
        const progress =
          job.hotels_total > 0 ? `${job.hotels_done}/${job.hotels_total}` : "starting";
        setMsg(`${job.state} — ${progress} (${job.duration_seconds}s)`);
        if (job.state === "completed" || job.state === "failed") {
          setPhase(job.state === "completed" ? "done" : "error");
          setMsg(
            job.state === "completed"
              ? `Done in ${job.duration_seconds}s — ${job.hotels_done}/${job.hotels_total} hotels`
              : `Failed: ${job.last_line ?? "unknown"}`,
          );
          router.refresh();
          return;
        }
      } catch (e) {
        setMsg(e instanceof Error ? e.message : String(e));
      }
    }
    setPhase("error");
    setMsg("Timed out polling for job result");
  }

  const busy = phase === "submitting" || phase === "running";

  return (
    <section className="rounded border border-line bg-white p-4">
      <header className="mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">
          Trigger scrape
        </h2>
        <p className="mt-1 text-xs text-subtle">
          Kicks off <code>run_job.py</code> on the jobs-api sidecar. Default window is{" "}
          <code>rolling:2</code> (current month + next 2).
        </p>
      </header>

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="OTA">
          <select
            className="w-full rounded border border-line px-2 py-1.5 text-sm"
            value={ota}
            onChange={(e) => setOta(e.target.value as typeof ota)}
            disabled={busy}
          >
            {OTAS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Length of stay">
          <select
            className="w-full rounded border border-line px-2 py-1.5 text-sm"
            value={los}
            onChange={(e) => setLos(Number(e.target.value) as 1 | 7 | 28)}
            disabled={busy}
          >
            {losOptions.map((n) => (
              <option key={n} value={n}>
                {n} night{n === 1 ? "" : "s"}
              </option>
            ))}
          </select>
          {ota === "branddotcom" && (
            <p className="mt-1 text-[11px] text-subtle">Brand.com has no 28-night data.</p>
          )}
        </Field>

        <Field label="Property">
          <select
            className="w-full rounded border border-line px-2 py-1.5 text-sm"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            disabled={busy}
          >
            <option value="">Portfolio ({subjects.length} hotels)</option>
            {subjects.map((s) => (
              <option key={s.subject_code} value={s.subject_code}>
                {s.display_name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={trigger}
          disabled={busy}
          className="flex items-center gap-2 rounded bg-ink px-3 py-1.5 text-sm font-medium text-white hover:bg-ink/90 disabled:opacity-60"
        >
          <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
          Run scrape
        </button>
        {msg && (
          <span
            className={
              "text-xs " +
              (phase === "error"
                ? "text-red-600"
                : phase === "done"
                  ? "text-green-700"
                  : "text-subtle")
            }
          >
            {msg}
          </span>
        )}
        {jobId && phase !== "idle" && (
          <span className="font-mono text-[10px] text-subtle">{jobId}</span>
        )}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-subtle">{label}</span>
      {children}
    </label>
  );
}
