"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Skull } from "lucide-react";

type Phase = "idle" | "submitting" | "ok" | "error";

export function JobKillButton({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [msg, setMsg] = useState("");

  async function kill() {
    if (
      !confirm(
        `Mark job ${jobId} as FAILED?\n\n` +
          "This only updates the DB row — it does NOT kill the underlying " +
          "OS process. Use this when a scrape is stuck because the process " +
          "died or hung. After it's marked failed, the Resume button " +
          "appears in the Recent Scrapes table and you can re-run the " +
          "remaining hotels from there.",
      )
    ) {
      return;
    }
    setPhase("submitting");
    setMsg("Killing…");
    try {
      const res = await fetch(`/api/jobs/${jobId}/kill`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setPhase("error");
        setMsg(data.error ?? `Failed (${res.status})`);
        return;
      }
      setPhase("ok");
      setMsg("Marked failed");
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
        onClick={kill}
        disabled={busy || phase === "ok"}
        title="Mark this stuck job as failed (DB only; doesn't kill the OS process)"
        className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:border-red-300 hover:bg-red-50 hover:text-red-700 disabled:opacity-60"
      >
        <Skull size={12} />
        Kill
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
