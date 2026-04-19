import { type RateCell as Cell } from "@/lib/queries";
import { fmtMoney } from "@/lib/utils";

export function RateCell({ cell }: { cell: Cell | null }) {
  if (!cell) return <span className="text-subtle">—</span>;

  if (!cell.is_available || cell.message === "rates.soldout") {
    return <span className="text-xs font-medium text-zinc-500">Sold out</span>;
  }

  if (cell.rate_value == null) {
    return <span className="text-subtle">—</span>;
  }

  return (
    <span className="font-medium tabular-nums" title={cellTitle(cell)}>
      {fmtMoney(cell.rate_value)}
    </span>
  );
}

function cellTitle(cell: Cell): string {
  const parts: string[] = [];
  if (cell.observation_ts) parts.push(`Scraped: ${cell.observation_ts}`);
  if (cell.extract_datetime) parts.push(`OTA last shopped: ${cell.extract_datetime}`);
  if (cell.shop_value != null) parts.push(`Stay total: ${fmtMoney(cell.shop_value)}`);
  if (cell.all_in_price != null) parts.push(`All-in: ${fmtMoney(cell.all_in_price)}`);
  return parts.join("\n");
}
