-- better-auth core schema (v1.x) — email/password only.
-- Tables: user, session, account, verification.
-- Identifiers are quoted because `user` is a Postgres reserved word.

SET LOCAL search_path = auth, public;

CREATE TABLE IF NOT EXISTS auth."user" (
    id              text PRIMARY KEY,
    name            text NOT NULL,
    email           text NOT NULL UNIQUE,
    "emailVerified" boolean NOT NULL DEFAULT false,
    image           text,
    "createdAt"     timestamptz NOT NULL DEFAULT now(),
    "updatedAt"     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth.session (
    id          text PRIMARY KEY,
    "userId"    text NOT NULL REFERENCES auth."user"(id) ON DELETE CASCADE,
    token       text NOT NULL UNIQUE,
    "expiresAt" timestamptz NOT NULL,
    "ipAddress" text,
    "userAgent" text,
    "createdAt" timestamptz NOT NULL DEFAULT now(),
    "updatedAt" timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS session_user_id_idx ON auth.session ("userId");
CREATE INDEX IF NOT EXISTS session_expires_at_idx ON auth.session ("expiresAt");

CREATE TABLE IF NOT EXISTS auth.account (
    id                       text PRIMARY KEY,
    "userId"                 text NOT NULL REFERENCES auth."user"(id) ON DELETE CASCADE,
    "accountId"              text NOT NULL,
    "providerId"             text NOT NULL,
    "accessToken"            text,
    "refreshToken"           text,
    "idToken"                text,
    "accessTokenExpiresAt"   timestamptz,
    "refreshTokenExpiresAt"  timestamptz,
    scope                    text,
    password                 text,
    "createdAt"              timestamptz NOT NULL DEFAULT now(),
    "updatedAt"              timestamptz NOT NULL DEFAULT now(),
    UNIQUE ("providerId", "accountId")
);
CREATE INDEX IF NOT EXISTS account_user_id_idx ON auth.account ("userId");

CREATE TABLE IF NOT EXISTS auth.verification (
    id          text PRIMARY KEY,
    identifier  text NOT NULL,
    value       text NOT NULL,
    "expiresAt" timestamptz NOT NULL,
    "createdAt" timestamptz NOT NULL DEFAULT now(),
    "updatedAt" timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS verification_identifier_idx ON auth.verification (identifier);
