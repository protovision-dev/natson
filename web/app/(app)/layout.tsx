import Link from "next/link";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line px-4">
        <div className="flex items-center gap-6">
          <span className="font-semibold tracking-tight">Natson Rate Intelligence</span>
          <nav className="flex gap-4 text-sm text-subtle">
            <Link href="/grid" className="hover:text-ink">Rate grid</Link>
            <Link href="/jobs" className="hover:text-ink">Jobs</Link>
          </nav>
        </div>
        <div className="text-xs text-subtle">{session.user.email}</div>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}
