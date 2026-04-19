"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { signUp } from "@/lib/auth-client";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    const { error } = await signUp.email({ email, password, name });
    setLoading(false);
    if (error) {
      setErr(error.message ?? "Sign-up failed");
      return;
    }
    router.push("/grid");
    router.refresh();
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <div className="rounded-lg border border-white/40 bg-white/85 p-6 shadow-xl backdrop-blur-sm">
        <h1 className="mb-6 text-2xl font-semibold">Create account</h1>
        <form onSubmit={onSubmit} className="space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm text-subtle">Name</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border border-line px-3 py-2"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-subtle">Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded border border-line px-3 py-2"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-subtle">Password</span>
            <input
              type="password"
              required
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border border-line px-3 py-2"
            />
            <span className="mt-1 block text-xs text-subtle">
              12 characters minimum, must include lowercase, uppercase, and a digit
            </span>
          </label>
          {err && <p className="text-sm text-red-600">{err}</p>}
          <button type="submit" disabled={loading} className="auth-button">
            {loading ? "Creating…" : "Create account"}
          </button>
        </form>
        <p className="mt-4 text-sm text-subtle">
          Already have an account?{" "}
          <Link href="/login" className="text-ink underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
