-- Fact tables: rates_current (thin, overwritten) + rate_observations
-- (fat, append-only monthly-partitioned time series).  Schema v3 §3.6–3.7.

-- -----------------------------------------------------------------------
-- rates_current: latest known rate per natural key.  Always overwritten.
-- One UPDATE per scrape per cell.  Metabase "what's the price now?" hits this.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rates_current (
    rate_current_id      BIGSERIAL   PRIMARY KEY,
    source_id            SMALLINT    NOT NULL REFERENCES sources(source_id),
    subject_hotel_id     INT         NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    competitor_hotel_pk  BIGINT      NOT NULL REFERENCES hotels(hotel_pk),
    stay_date            DATE        NOT NULL,
    checkout_date        DATE        NOT NULL,
    los                  SMALLINT    NOT NULL,
    persons              SMALLINT    NOT NULL,

    rate_value           NUMERIC(10,2),
    shop_value           NUMERIC(10,2),
    all_in_price         NUMERIC(10,2),

    vat                  NUMERIC(10,2),
    vat_incl             BOOLEAN,
    city_tax             NUMERIC(10,2),
    city_tax_incl        BOOLEAN,
    other_taxes          NUMERIC(10,2),
    other_taxes_incl     BOOLEAN,

    room_name            TEXT,
    room_type            TEXT,
    cema_category        TEXT,
    max_persons          SMALLINT,
    mealtype_included    SMALLINT,
    membershiptype       SMALLINT,

    best_flex            BOOLEAN,
    cancellable          BOOLEAN,
    cancellation         BOOLEAN,
    is_baserate          BOOLEAN,
    is_out_of_sync       BOOLEAN,
    platform             SMALLINT,
    is_available         BOOLEAN     DEFAULT TRUE,

    booking_url          TEXT,
    extract_datetime     TIMESTAMPTZ,
    message              TEXT,

    leadtime_days        INT,
    market_demand_pct    NUMERIC(5,2),

    scrape_run_id        BIGINT      NOT NULL,
    first_observed_at    TIMESTAMPTZ NOT NULL,
    last_scraped_at      TIMESTAMPTZ NOT NULL,
    last_changed_at      TIMESTAMPTZ NOT NULL,

    UNIQUE (source_id, subject_hotel_id, competitor_hotel_pk, stay_date, los, persons)
);

CREATE INDEX IF NOT EXISTS idx_rc_subject_date  ON rates_current (subject_hotel_id, stay_date);
CREATE INDEX IF NOT EXISTS idx_rc_source_date   ON rates_current (source_id, stay_date);
CREATE INDEX IF NOT EXISTS idx_rc_competitor    ON rates_current (competitor_hotel_pk, stay_date);
CREATE INDEX IF NOT EXISTS idx_rc_los           ON rates_current (los, persons);

-- -----------------------------------------------------------------------
-- rate_observations: one row per scrape per key, append-only.
-- Partitioned monthly by observation_date (the scrape date).  Child
-- partitions are pre-created in 0006 and auto-rolled monthly by 0007.
--
-- Idempotency: a same-day re-scrape UPSERTs the row for that
-- observation_date (not a second row) — ON CONFLICT DO UPDATE in the
-- ingest path.  Sub-daily resolution requires switching the unique
-- key to include observation_ts (schema v3 §9).
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rate_observations (
    observation_id       BIGSERIAL,
    observation_date     DATE        NOT NULL,
    observation_ts       TIMESTAMPTZ NOT NULL,

    source_id            SMALLINT    NOT NULL,
    subject_hotel_id     INT         NOT NULL,
    competitor_hotel_pk  BIGINT      NOT NULL,
    stay_date            DATE        NOT NULL,
    checkout_date        DATE        NOT NULL,
    los                  SMALLINT    NOT NULL,
    persons              SMALLINT    NOT NULL,

    rate_value           NUMERIC(10,2),
    shop_value           NUMERIC(10,2),
    all_in_price         NUMERIC(10,2),

    vat                  NUMERIC(10,2),
    vat_incl             BOOLEAN,
    city_tax             NUMERIC(10,2),
    city_tax_incl        BOOLEAN,
    other_taxes          NUMERIC(10,2),
    other_taxes_incl     BOOLEAN,

    room_name            TEXT,
    room_type            TEXT,
    cema_category        TEXT,
    max_persons          SMALLINT,
    mealtype_included    SMALLINT,
    membershiptype       SMALLINT,

    best_flex            BOOLEAN,
    cancellable          BOOLEAN,
    cancellation         BOOLEAN,
    is_baserate          BOOLEAN,
    is_out_of_sync       BOOLEAN,
    platform             SMALLINT,
    is_available         BOOLEAN     NOT NULL DEFAULT TRUE,

    booking_url          TEXT,
    extract_datetime     TIMESTAMPTZ,
    message              TEXT,
    leadtime_days        INT,
    market_demand_pct    NUMERIC(5,2),

    prior_rate_value     NUMERIC(10,2),
    rate_delta           NUMERIC(10,2),
    changed_from_prior   BOOLEAN     NOT NULL DEFAULT FALSE,

    scrape_run_id        BIGINT      NOT NULL,

    PRIMARY KEY (observation_id, observation_date)
) PARTITION BY RANGE (observation_date);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ro_natural_key
    ON rate_observations (source_id, subject_hotel_id, competitor_hotel_pk,
                          stay_date, los, persons, observation_date);

CREATE INDEX IF NOT EXISTS idx_ro_stay_trend
    ON rate_observations (subject_hotel_id, stay_date, source_id, los, observation_date DESC);

CREATE INDEX IF NOT EXISTS idx_ro_leadtime
    ON rate_observations (subject_hotel_id, stay_date, leadtime_days);
