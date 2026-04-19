"use client";
import { useEffect, useState, useTransition } from "react";
import { Trash2 } from "lucide-react";

type AllowedDomain = { domain: string; added_by: string; added_at: string };

export function AllowedDomainsCard() {
  const [domains, setDomains] = useState<AllowedDomain[]>([]);
  const [input, setInput] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, startSubmit] = useTransition();

  async function load() {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/allowed-domains");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setDomains(data.domains);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function add() {
    if (!input.trim()) return;
    setErr(null);
    startSubmit(async () => {
      try {
        const res = await fetch("/api/admin/allowed-domains", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ domain: input }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
        setInput("");
        await load();
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    });
  }

  function remove(domain: string) {
    setErr(null);
    startSubmit(async () => {
      try {
        const res = await fetch(`/api/admin/allowed-domains/${encodeURIComponent(domain)}`, {
          method: "DELETE",
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.error ?? `HTTP ${res.status}`);
        }
        await load();
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    });
  }

  return (
    <section className="rounded border border-line bg-white p-4">
      <header className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">
          Allowed signup domains
        </h2>
        <span className="text-xs text-subtle">
          {domains.length} domain{domains.length === 1 ? "" : "s"}
        </span>
      </header>

      <p className="mb-3 text-xs text-subtle">
        Only emails from these domains can register. Admins (set in <code>ADMIN_EMAILS</code>)
        bypass this list and can always sign up.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
        className="mb-3 flex gap-2"
      >
        <input
          type="text"
          placeholder="example.com"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="flex-1 rounded border border-line px-3 py-1.5 text-sm"
          disabled={submitting}
        />
        <button
          type="submit"
          disabled={submitting || !input.trim()}
          className="rounded bg-ink px-3 py-1.5 text-sm font-medium text-white hover:bg-ink/90 disabled:opacity-60"
        >
          Add
        </button>
      </form>

      {err && <p className="mb-3 text-xs text-red-600">{err}</p>}

      {loading ? (
        <p className="text-sm text-subtle">Loading…</p>
      ) : domains.length === 0 ? (
        <p className="text-sm text-subtle">
          No domains yet. Only admins can sign up until you add at least one.
        </p>
      ) : (
        <ul className="divide-y divide-line text-sm">
          {domains.map((d) => (
            <li key={d.domain} className="flex items-center justify-between py-2">
              <div>
                <div className="font-medium">{d.domain}</div>
                <div className="text-xs text-subtle">
                  added by {d.added_by} • {new Date(d.added_at).toLocaleString()}
                </div>
              </div>
              <button
                onClick={() => remove(d.domain)}
                disabled={submitting}
                className="rounded p-1.5 text-subtle hover:bg-zinc-100 hover:text-red-600 disabled:opacity-60"
                aria-label={`Remove ${d.domain}`}
                title="Remove"
              >
                <Trash2 size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
