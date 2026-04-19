import { describe, expect, it } from "vitest";
import { normalizeDomain } from "@/lib/allowed-domains";

describe("normalizeDomain", () => {
  it("lowercases + strips a leading @", () => {
    expect(normalizeDomain("@Example.COM")).toBe("example.com");
    expect(normalizeDomain("Example.COM")).toBe("example.com");
  });

  it("accepts subdomains", () => {
    expect(normalizeDomain("rates.example.com")).toBe("rates.example.com");
  });

  it("rejects bare hostnames + invalid characters", () => {
    expect(normalizeDomain("not-a-domain")).toBeNull();
    expect(normalizeDomain("space domain.com")).toBeNull();
    expect(normalizeDomain("trailing-dot.")).toBeNull();
    expect(normalizeDomain("")).toBeNull();
  });
});
