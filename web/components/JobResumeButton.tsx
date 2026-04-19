"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { RotateCcw } from "lucide-react";

type Props = {
  jobId: string;
  hotelsDone: number;
  hotelsTotal: number;
};

type Phase = "idle" | "submitting" | "ok" | "error";

export function JobResumeButton({ jobId, hotelsDone, hotelsTotal }: Props) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [msg, setMsg] = useState("");

  const remaining = Math.max(0, hotelsTotal - hotelsDone);
  if (remaining === 0) return null;

  async function resume() {
    if (
      !confirm(
        `Resume job ${jobId}?\n\nThis re-scrapes hotels ${hotelsDone + 1}–${hotelsTotal} ` +
          `(${remaining} hotel${remaining === 1 ? "" : "s"}) using the original spec.`,
      )
    ) {
      return;
    }
    setPhase("submitting");
    setMsg("Submitting…");
    try {
      const res = await fetch(`/api/jobs/${jobId}/resume`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setPhase("error");
        setMsg(data.error ?? `Failed (${res.status})`);
        return;
      }
      setPhase("ok");
      setMsg(`→ ${data.job_id} (${remaining} hotel${remaining === 1 ? "" : "s"})`);
      router.refresh();
    } catch (e) {
      setPhase("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  const busy = phase === "submitting";
  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={resume}
        disabled={busy}
        title={`Re-scrape hotels ${hotelsDone + 1}–${hotelsTotal}`}
        className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-zinc-100 disabled:opacity-60"
      >
        <RotateCcw size={12} className={busy ? "animate-spin" : ""} />
        Resume
      </button>
      {msg && (
        <span
          className={
            "text-[11px] " +
            (phase === "error" ? "text-red-600" : phase === "ok" ? "text-green-700" : "text-subtle")
          }
        >
          {msg}
        </span>
      )}
    </span>
  );
}
