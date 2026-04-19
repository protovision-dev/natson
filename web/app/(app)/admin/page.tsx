import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "@/lib/auth";
import { isAdmin } from "@/lib/admin";
import { fetchSubjects } from "@/lib/queries";
import { AllowedDomainsCard } from "@/components/AllowedDomainsCard";
import { AdminScrapeForm } from "@/components/AdminScrapeForm";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");
  if (!isAdmin(session.user.email)) {
    return (
      <div className="p-8">
        <h1 className="mb-2 text-xl font-semibold">Forbidden</h1>
        <p className="text-sm text-subtle">
          Your account isn&apos;t in <code>ADMIN_EMAILS</code>.
        </p>
      </div>
    );
  }

  const subjects = await fetchSubjects();

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <h1 className="text-lg font-semibold">Admin</h1>
      <AdminScrapeForm subjects={subjects} />
      <AllowedDomainsCard />
    </div>
  );
}
