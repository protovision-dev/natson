-- Dimension tables for the rate-tracking schema (schema v3 §3.1–3.5).
-- All idempotent — re-runs are no-ops after the first successful apply.

-- -----------------------------------------------------------------------
-- sources: one row per OTA / data source we ingest from.
-- Adding a new source = one row here + a corresponding mapping in
-- scraper/db/mapping.py. Nothing else changes in the schema.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    source_id    SMALLSERIAL PRIMARY KEY,
    source_code  TEXT        NOT NULL UNIQUE,
    source_name  TEXT        NOT NULL,
    vendor       TEXT        NOT NULL DEFAULT 'lighthouse',
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO sources (source_code, source_name) VALUES
    ('booking', 'Booking.com via Lighthouse'),
    ('brand',   'Brand.com via Lighthouse')
ON CONFLICT (source_code) DO NOTHING;

-- -----------------------------------------------------------------------
-- hotels: one row per physical property (subject or competitor).
-- external_hotel_id = Lighthouse's hotelinfo_id, which is shared across
-- OTAs — confirmed against 2026-04-17 booking vs brand snapshots.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hotels (
    hotel_pk           BIGSERIAL   PRIMARY KEY,
    external_hotel_id  TEXT        NOT NULL UNIQUE,
    name               TEXT        NOT NULL,
    stars              SMALLINT,
    country            TEXT,
    latitude           NUMERIC(10,7),
    longitude          NUMERIC(10,7),
    hotel_group        TEXT,
    booking_base_url   TEXT,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attributes         JSONB
);

CREATE INDEX IF NOT EXISTS idx_hotels_name_trgm
    ON hotels USING GIN (name gin_trgm_ops);

-- -----------------------------------------------------------------------
-- subject_hotels: our portfolio. One row per subscription we own.
-- Direct FK to hotels (each subject IS a physical hotel row).
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subject_hotels (
    subject_hotel_id       SERIAL      PRIMARY KEY,
    hotel_pk               BIGINT      NOT NULL UNIQUE REFERENCES hotels(hotel_pk),
    internal_code          TEXT        NOT NULL UNIQUE,
    display_name           TEXT        NOT NULL,
    city                   TEXT,
    state                  TEXT,
    country                TEXT,
    brand                  TEXT,
    lighthouse_compset_id  INT,
    is_active              BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------
-- compset_members: which competitors belong to which subject.
-- UNION across sources — we never auto-close members based on a single-
-- source payload (validated: Lighthouse returns different compsets per
-- OTA for some subjects). Close only via admin CLI when truly removed.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compset_members (
    compset_member_id    BIGSERIAL   PRIMARY KEY,
    subject_hotel_id     INT         NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    competitor_hotel_pk  BIGINT      NOT NULL REFERENCES hotels(hotel_pk),
    is_own               BOOLEAN     NOT NULL DEFAULT FALSE,
    valid_from           DATE        NOT NULL,
    valid_to             DATE,
    UNIQUE (subject_hotel_id, competitor_hotel_pk, valid_from)
);

CREATE INDEX IF NOT EXISTS idx_compset_active
    ON compset_members (subject_hotel_id)
    WHERE valid_to IS NULL;

-- -----------------------------------------------------------------------
-- stay_parameters: (los, persons) combinations we track.
-- Reference-only; the fact tables carry los/persons directly.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stay_parameters (
    stay_param_id  SMALLSERIAL PRIMARY KEY,
    los            SMALLINT    NOT NULL,
    persons        SMALLINT    NOT NULL,
    label          TEXT        NOT NULL,
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    UNIQUE (los, persons)
);

INSERT INTO stay_parameters (los, persons, label) VALUES
    (1,  2, '1-night / 2 adults'),
    (7,  2, '7-night / 2 adults'),
    (28, 2, '28-night / 2 adults')
ON CONFLICT (los, persons) DO NOTHING;
