"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { RefreshCw } from "lucide-react";

type Props = {
  subject: string;
  source: string;
  los: number;
  persons: number;
  from: string;
  to: string;
};

type Phase = "idle" | "submitting" | "running" | "done" | "error";

export function RefreshButton(p: Props) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [msg, setMsg] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);

  async function trigger() {
    setPhase("submitting");
    setMsg("Triggering scrape…");
    try {
      const dates = p.from === p.to ? p.from : `${p.from}:${p.to}`;
      const res = await fetch("/api/jobs/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subjects: [p.subject],
          dates,
          ota: p.source === "brand" ? "branddotcom" : "bookingdotcom",
          los: p.los,
          persons: p.persons,
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
      poll(data.job_id);
    } catch (e) {
      setPhase("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  async function poll(id: string) {
    const start = Date.now();
    const TIMEOUT_MS = 10 * 60 * 1000;
    while (Date.now() - start < TIMEOUT_MS) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const res = await fetch(`/api/jobs/${id}`);
        if (res.status === 404) {
          setMsg(`Waiting for job ${id} to register…`);
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
    <div className="flex items-center gap-2">
      <button
        onClick={trigger}
        disabled={busy}
        className="flex items-center gap-1.5 rounded bg-ink px-3 py-1.5 text-xs font-medium text-white hover:bg-ink/90 disabled:opacity-60"
      >
        <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
        Refresh rates
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
  );
}
