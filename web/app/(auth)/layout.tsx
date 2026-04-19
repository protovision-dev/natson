/**
 * Wraps /login and /signup with the WOPR background image at 50%
 * opacity. Form children sit in their own translucent card so the
 * photograph stays visible without sacrificing readability.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen">
      <div
        aria-hidden
        className="fixed inset-0 -z-10 bg-cover bg-center bg-no-repeat opacity-50"
        style={{ backgroundImage: "url('/login-bg.png')" }}
      />
      {children}
    </div>
  );
}
