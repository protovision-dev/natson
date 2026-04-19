-- Isolated schema for better-auth tables used by the Next.js web app.
-- Roles + grants live in db/bootstrap-app-roles.sh (env-driven passwords).
CREATE SCHEMA IF NOT EXISTS auth;
