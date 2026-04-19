import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
        ],
      },
      colors: {
        ink: "#1f2330",
        subtle: "#6b7280",
        line: "#e5e7eb",
        ownRow: "#fff7ed",
      },
    },
  },
  plugins: [],
} satisfies Config;
