import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtMoney(v: number | null | undefined, currency = "USD"): string {
  if (v == null) return "—";
  const sign = currency === "USD" ? "$" : "";
  return `${sign} ${Math.round(v).toLocaleString("en-US")}`;
}

export function fmtDateShort(d: Date | string): string {
  const dt = typeof d === "string" ? new Date(d + "T00:00:00") : d;
  return dt.toLocaleDateString("en-US", { weekday: "short", month: "2-digit", day: "2-digit" });
}

export function relativeTime(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const t = typeof iso === "string" ? new Date(iso) : iso;
  const diffMs = Date.now() - t.getTime();
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs} hr${hrs === 1 ? "" : "s"} ago`;
  const days = Math.round(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}
