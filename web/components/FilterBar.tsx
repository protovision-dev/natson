"use client";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useTransition } from "react";

type Subject = { subject_code: string; display_name: string };
type Source = { source_code: string };

const LOS_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 14, 28];
const PERSON_OPTIONS = [1, 2, 3, 4];

const MONTH_LABEL = new Intl.DateTimeFormat("en-US", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

function fmtMonth(ym: string): string {
  // ym is "YYYY-MM"; build a UTC date so the label matches the key.
  const [y, m] = ym.split("-").map(Number);
  return MONTH_LABEL.format(new Date(Date.UTC(y, m - 1, 1)));
}

export function FilterBar({
  subjects,
  sources,
  months,
  current,
}: {
  subjects: Subject[];
  sources: Source[];
  months: string[];
  current: {
    subject: string;
    source: string;
    los: number;
    persons: number;
    month: string;
  };
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, start] = useTransition();

  function update(patch: Partial<typeof current>) {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      sp.set(k, String(v));
    }
    // Changing subject/source can change which months have data, so let
    // the server re-derive the month when those filters change.
    if (patch.subject || patch.source) sp.delete("month");
    // Drop any legacy from/to so the new month selector is the source of truth.
    sp.delete("from");
    sp.delete("to");
    start(() => {
      router.push(`${pathname}?${sp.toString()}`);
    });
  }

  return (
    <div
      className={
        "flex flex-wrap items-center gap-2 " + (pending ? "opacity-60 transition-opacity" : "")
      }
    >
      <Select label="Subject" value={current.subject} onChange={(v) => update({ subject: v })}>
        {subjects.map((s) => (
          <option key={s.subject_code} value={s.subject_code}>
            {s.display_name}
          </option>
        ))}
      </Select>
      <Select label="OTA" value={current.source} onChange={(v) => update({ source: v })}>
        {sources.map((s) => (
          <option key={s.source_code} value={s.source_code}>
            {s.source_code}
          </option>
        ))}
      </Select>
      <Select
        label="Nights"
        value={String(current.los)}
        onChange={(v) => update({ los: Number(v) })}
      >
        {LOS_OPTIONS.map((n) => (
          <option key={n} value={n}>
            {n} night{n === 1 ? "" : "s"}
          </option>
        ))}
      </Select>
      <Select
        label="Guests"
        value={String(current.persons)}
        onChange={(v) => update({ persons: Number(v) })}
      >
        {PERSON_OPTIONS.map((n) => (
          <option key={n} value={n}>
            {n} guest{n === 1 ? "" : "s"}
          </option>
        ))}
      </Select>
      <Select label="From month" value={current.month} onChange={(v) => update({ month: v })}>
        {months.length === 0 ? (
          <option value={current.month}>{fmtMonth(current.month)}</option>
        ) : (
          months.map((m) => (
            <option key={m} value={m}>
              {fmtMonth(m)}
            </option>
          ))
        )}
      </Select>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-1 rounded border border-line bg-white px-2 py-1 text-xs">
      <span className="text-subtle">{label}:</span>
      <select
        className="bg-transparent text-xs font-medium outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {children}
      </select>
    </label>
  );
}
