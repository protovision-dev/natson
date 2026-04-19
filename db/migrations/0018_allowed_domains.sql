-- Allow-list of email domains permitted to register through better-auth.
-- Lives in the auth schema so the natson_auth role (which already owns
-- the schema) can read/write without extra grants.
--
-- Bootstrap behavior is enforced in code (lib/auth.ts hooks.before):
--   1. Admin emails (.env ADMIN_EMAILS) can always sign up.
--   2. Other emails: their domain must appear in this table.
-- An empty table therefore lets only admins onboard until an admin
-- adds at least one domain via /admin.

CREATE TABLE IF NOT EXISTS auth.allowed_domains (
    domain      TEXT PRIMARY KEY,
    added_by    TEXT NOT NULL,        -- admin email that added the row
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Domains are stored lowercase; enforce that at the DB layer too so a
-- sloppy INSERT can't slip past.
CREATE OR REPLACE FUNCTION auth._lowercase_domain()
RETURNS TRIGGER AS $$
BEGIN
    NEW.domain := LOWER(NEW.domain);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS allowed_domains_lowercase ON auth.allowed_domains;
CREATE TRIGGER allowed_domains_lowercase
    BEFORE INSERT OR UPDATE ON auth.allowed_domains
    FOR EACH ROW
    EXECUTE FUNCTION auth._lowercase_domain();
