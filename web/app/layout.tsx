import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Natson Rate Intelligence",
  description: "Competitive rate grid for Natson Hotels portfolio",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
