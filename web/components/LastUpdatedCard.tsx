import { relativeTime } from "@/lib/utils";

export function LastUpdatedCard({
  observation,
  extract,
}: {
  observation: string | null;
  extract: string | null;
}) {
  return (
    <div className="rounded border border-line bg-white px-3 py-1.5 text-xs">
      <div>
        <span className="text-subtle">Our scrape:</span>{" "}
        <span className="font-medium">{relativeTime(observation)}</span>
      </div>
      <div>
        <span className="text-subtle">OTA extract:</span>{" "}
        <span className="font-medium">{relativeTime(extract)}</span>
      </div>
    </div>
  );
}
