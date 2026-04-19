export function MarketDemandCell({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-subtle">—</span>;
  const v = Math.max(0, Math.min(100, Number(pct)));
  // gradient: blue (low) → orange (mid) → red (high)
  const color = v >= 80 ? "bg-red-500" : v >= 50 ? "bg-orange-400" : "bg-blue-400";
  return (
    <div className="flex items-center gap-2">
      <span className="w-9 text-xs font-medium tabular-nums">{Math.round(v)}%</span>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-zinc-200">
        <div className={"h-full " + color} style={{ width: `${v}%` }} />
      </div>
    </div>
  );
}
