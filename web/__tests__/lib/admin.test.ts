import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { emailDomain, isAdmin } from "@/lib/admin";

describe("isAdmin", () => {
  const original = process.env.ADMIN_EMAILS;
  beforeEach(() => {
    process.env.ADMIN_EMAILS = "drew@natson.local, ops@example.com";
  });
  afterEach(() => {
    process.env.ADMIN_EMAILS = original;
  });

  it("matches case-insensitively", () => {
    expect(isAdmin("Drew@Natson.Local")).toBe(true);
    expect(isAdmin("ops@example.com")).toBe(true);
  });

  it("rejects non-admin emails", () => {
    expect(isAdmin("alice@example.com")).toBe(false);
  });

  it("returns false for null/empty", () => {
    expect(isAdmin(null)).toBe(false);
    expect(isAdmin(undefined)).toBe(false);
    expect(isAdmin("")).toBe(false);
  });

  it("returns false when env var is unset", () => {
    delete process.env.ADMIN_EMAILS;
    expect(isAdmin("drew@natson.local")).toBe(false);
  });
});

describe("emailDomain", () => {
  it("extracts and lowercases the domain", () => {
    expect(emailDomain("alice@Example.COM")).toBe("example.com");
    expect(emailDomain("foo+tag@sub.example.org")).toBe("sub.example.org");
  });

  it("returns null on malformed input", () => {
    expect(emailDomain("no-at-sign")).toBeNull();
    expect(emailDomain("@nothing-before")).toBeNull();
    expect(emailDomain("nothing-after@")).toBeNull();
  });
});
