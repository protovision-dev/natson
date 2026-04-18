# Hotel Rate Tracking — Database Schema (v3)

**Target DB:** PostgreSQL 15+ with `pg_partman` extension
**Purpose:** Ingest daily Lighthouse scrapes of hotel rates across multiple sources (booking.com, brand.com, future) and multiple LOS values. Capture a daily time series for every key, track changes over time, and serve Metabase dashboards.

---

## 1. Design principles

1. **Star schema.** Dimensions + two fact tables: `rates_current` (thin, overwritten) and `rate_observations` (fat, append-only daily time series).
2. **Source is a column on the fact tables, not a partition of the data.** Adding a new source = one row in `sources`.
3. **Shared `hotel_id` across sources** → single `hotels` dimension row per physical property. Same competitor on booking.com and brand.com has one `hotel_pk`.
4. **LOS, persons, source are first-class fact-table dimensions.** Each combination is its own observation.
5. **Always-insert observations.** Daily time series, even when the rate didn't move.
6. **Partition by month.** 3 years of hot data fits comfortably.
7. **Keep raw JSON 90 days hot, archive cold after.**

---

## 2. Entity model

```
sources (booking, brand, ...)

subject_hotels (our 10 properties) ───┐
                                      │ FK
                                      ▼
                          hotels (all hotels, one row per physical property)
                                      ▲
                                      │ FK
                    compset_members (which competitors belong to which subject)

rates_current      ← one row per (source, subject, competitor, stay_date, LOS, persons). Overwritten.
rate_observations  ← one row per scrape per key. Append-only. Partitioned by month.
rate_changes       ← materialized view, derived from observations.
scrape_runs        ← audit trail per scrape job.
raw_payloads       ← original JSON, hot 90d, cold after.
```

---

## 3. Tables

### 3.1 Dimension: `sources`

```sql
CREATE TABLE sources (
    source_id        SMALLSERIAL PRIMARY KEY,
    source_code      TEXT NOT NULL UNIQUE,      -- 'booking', 'brand', 'expedia'
    source_name      TEXT NOT NULL,
    vendor           TEXT NOT NULL DEFAULT 'lighthouse',
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO sources (source_code, source_name) VALUES
    ('booking', 'Booking.com via Lighthouse'),
    ('brand',   'Brand.com via Lighthouse');
```

### 3.2 Dimension: `hotels`

**One row per physical hotel.** Keyed on `external_hotel_id` (the Lighthouse ID, shared across sources). Ingest bumps `last_seen_at` and updates metadata from whichever source's JSON is being processed — data should be consistent, but if it differs we take the most recent.

```sql
CREATE TABLE hotels (
    hotel_pk             BIGSERIAL PRIMARY KEY,
    external_hotel_id    TEXT NOT NULL UNIQUE,   -- Lighthouse hotel_id, e.g. '345062', '183310'
    name                 TEXT NOT NULL,
    stars                SMALLINT,
    country              TEXT,
    latitude             NUMERIC(10,7),
    longitude            NUMERIC(10,7),
    hotel_group          TEXT,
    booking_base_url     TEXT,
    first_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attributes           JSONB                   -- any additional per-hotel fields
);

CREATE INDEX idx_hotels_name_trgm ON hotels USING GIN (name gin_trgm_ops);
```

### 3.3 Dimension: `subject_hotels`

Our own properties. Direct FK to `hotels` — one `hotel_pk` per subject.

```sql
CREATE TABLE subject_hotels (
    subject_hotel_id     SERIAL PRIMARY KEY,
    hotel_pk             BIGINT NOT NULL UNIQUE REFERENCES hotels(hotel_pk),
    internal_code        TEXT NOT NULL UNIQUE,   -- your stable code, e.g. 'ESA-AUS-LAKE'
    display_name         TEXT NOT NULL,
    city                 TEXT,
    state                TEXT,
    country              TEXT,
    brand                TEXT,                    -- 'Extended Stay America', 'Motel 6'
    lighthouse_compset_id INT,                    -- the compset id Lighthouse uses
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3.4 Bridge: `compset_members`

Which competitors belong to which subject. Not per-source — the compset is defined by Lighthouse and shared across booking.com and brand.com scrapes. If brand.com happens to return no data for a competitor (because they're not a chain), that just shows up as missing observations, not a different compset.

```sql
CREATE TABLE compset_members (
    compset_member_id    BIGSERIAL PRIMARY KEY,
    subject_hotel_id     INT NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    competitor_hotel_pk  BIGINT NOT NULL REFERENCES hotels(hotel_pk),
    is_own               BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from           DATE NOT NULL,
    valid_to             DATE,                   -- NULL = still in compset
    UNIQUE (subject_hotel_id, competitor_hotel_pk, valid_from)
);

CREATE INDEX idx_compset_active
    ON compset_members (subject_hotel_id)
    WHERE valid_to IS NULL;
```

### 3.5 Dimension: `stay_parameters` (optional)

```sql
CREATE TABLE stay_parameters (
    stay_param_id        SMALLSERIAL PRIMARY KEY,
    los                  SMALLINT NOT NULL,
    persons              SMALLINT NOT NULL,
    label                TEXT NOT NULL,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (los, persons)
);

INSERT INTO stay_parameters (los, persons, label) VALUES
    (1,  2, '1-night / 2 adults'),
    (7,  2, '7-night / 2 adults'),
    (28, 2, '28-night / 2 adults');
```

### 3.6 Fact: `rates_current`

**One row per unique key. Overwritten on every scrape.** Natural key: `(source, subject, competitor, stay_date, LOS, persons)`.

```sql
CREATE TABLE rates_current (
    rate_current_id      BIGSERIAL PRIMARY KEY,
    source_id            SMALLINT NOT NULL REFERENCES sources(source_id),
    subject_hotel_id     INT      NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    competitor_hotel_pk  BIGINT   NOT NULL REFERENCES hotels(hotel_pk),
    stay_date            DATE     NOT NULL,
    checkout_date        DATE     NOT NULL,
    los                  SMALLINT NOT NULL,
    persons              SMALLINT NOT NULL,

    -- rate (all USD)
    rate_value           NUMERIC(10,2),          -- nightly
    shop_value           NUMERIC(10,2),          -- total stay
    all_in_price         NUMERIC(10,2),          -- shop + non-included taxes/fees, cross-source comparable

    -- tax / fee detail
    vat                  NUMERIC(10,2),
    vat_incl             BOOLEAN,
    city_tax             NUMERIC(10,2),
    city_tax_incl        BOOLEAN,
    other_taxes          NUMERIC(10,2),
    other_taxes_incl     BOOLEAN,

    -- room detail
    room_name            TEXT,
    room_type            TEXT,
    cema_category        TEXT,
    max_persons          SMALLINT,
    mealtype_included    SMALLINT,
    membershiptype       SMALLINT,

    -- flags
    best_flex            BOOLEAN,
    cancellable          BOOLEAN,
    cancellation         BOOLEAN,
    is_baserate          BOOLEAN,
    is_out_of_sync       BOOLEAN,
    platform             SMALLINT,
    is_available         BOOLEAN DEFAULT TRUE,

    -- provenance
    booking_url          TEXT,
    extract_datetime     TIMESTAMPTZ,
    message              TEXT,

    -- demand / leadtime
    leadtime_days        INT,
    market_demand_pct    NUMERIC(5,2),

    -- metadata
    scrape_run_id        BIGINT   NOT NULL,
    first_observed_at    TIMESTAMPTZ NOT NULL,
    last_scraped_at      TIMESTAMPTZ NOT NULL,
    last_changed_at      TIMESTAMPTZ NOT NULL,

    UNIQUE (source_id, subject_hotel_id, competitor_hotel_pk, stay_date, los, persons)
);

CREATE INDEX idx_rc_subject_date  ON rates_current (subject_hotel_id, stay_date);
CREATE INDEX idx_rc_source_date   ON rates_current (source_id, stay_date);
CREATE INDEX idx_rc_competitor    ON rates_current (competitor_hotel_pk, stay_date);
CREATE INDEX idx_rc_los           ON rates_current (los, persons);
```

### 3.7 Fact: `rate_observations` ⭐ (daily time series)

**One row per scrape per key, always inserted.** Partitioned monthly on `observation_date`.

```sql
CREATE TABLE rate_observations (
    observation_id       BIGSERIAL,
    observation_date     DATE NOT NULL,          -- partition key; the scrape_date
    observation_ts       TIMESTAMPTZ NOT NULL,   -- exact scrape time

    source_id            SMALLINT NOT NULL,
    subject_hotel_id     INT      NOT NULL,
    competitor_hotel_pk  BIGINT   NOT NULL,
    stay_date            DATE     NOT NULL,
    checkout_date        DATE     NOT NULL,
    los                  SMALLINT NOT NULL,
    persons              SMALLINT NOT NULL,

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
    is_available         BOOLEAN NOT NULL DEFAULT TRUE,

    booking_url          TEXT,
    extract_datetime     TIMESTAMPTZ,
    message              TEXT,
    leadtime_days        INT,
    market_demand_pct    NUMERIC(5,2),

    -- change info (computed on insert, denormalized for Metabase)
    prior_rate_value     NUMERIC(10,2),
    rate_delta           NUMERIC(10,2),
    changed_from_prior   BOOLEAN NOT NULL DEFAULT FALSE,

    scrape_run_id        BIGINT NOT NULL,

    PRIMARY KEY (observation_id, observation_date)
) PARTITION BY RANGE (observation_date);

CREATE UNIQUE INDEX idx_ro_natural_key
    ON rate_observations (source_id, subject_hotel_id, competitor_hotel_pk,
                          stay_date, los, persons, observation_date);

CREATE INDEX idx_ro_stay_trend
    ON rate_observations (subject_hotel_id, stay_date, source_id, los, observation_date DESC);

CREATE INDEX idx_ro_leadtime
    ON rate_observations (subject_hotel_id, stay_date, leadtime_days);

-- Bootstrap partitions
CREATE TABLE rate_observations_2026_04 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE rate_observations_2026_05 PARTITION OF rate_observations
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
```

Automate partition management:

```sql
CREATE EXTENSION pg_partman;
SELECT partman.create_parent(
    p_parent_table => 'public.rate_observations',
    p_control      => 'observation_date',
    p_type         => 'native',
    p_interval     => '1 month',
    p_premake      => 6
);
```

### 3.8 Derived: `rate_changes` (materialized view)

```sql
CREATE MATERIALIZED VIEW rate_changes AS
SELECT
    observation_id, observation_date, observation_ts,
    source_id, subject_hotel_id, competitor_hotel_pk,
    stay_date, los, persons,
    prior_rate_value, rate_value, rate_delta,
    CASE
        WHEN prior_rate_value IS NULL      THEN 'new'
        WHEN rate_value IS NULL            THEN 'unavailable'
        WHEN rate_value > prior_rate_value THEN 'price_up'
        WHEN rate_value < prior_rate_value THEN 'price_down'
        ELSE                                    'unchanged'
    END AS change_type,
    room_name, room_type
FROM rate_observations
WHERE changed_from_prior = TRUE;

CREATE UNIQUE INDEX idx_rc_pk   ON rate_changes (observation_id, observation_date);
CREATE INDEX idx_rc_stay        ON rate_changes (subject_hotel_id, stay_date, source_id);
CREATE INDEX idx_rc_obs         ON rate_changes (observation_date);

-- REFRESH MATERIALIZED VIEW CONCURRENTLY rate_changes;  -- nightly post-scrape
```

### 3.9 Audit: `scrape_runs` & `scrape_run_hotels`

```sql
CREATE TABLE scrape_runs (
    scrape_run_id        BIGSERIAL PRIMARY KEY,
    source_id            SMALLINT NOT NULL REFERENCES sources(source_id),
    scrape_date          DATE NOT NULL,
    started_at           TIMESTAMPTZ NOT NULL,
    completed_at         TIMESTAMPTZ,
    hotels_scraped       INT,
    hotels_failed        INT,
    status               TEXT NOT NULL DEFAULT 'running',
    notes                TEXT
);

CREATE INDEX idx_scrape_runs_source_date ON scrape_runs (source_id, scrape_date DESC);

CREATE TABLE scrape_run_hotels (
    scrape_run_hotel_id  BIGSERIAL PRIMARY KEY,
    scrape_run_id        BIGINT NOT NULL REFERENCES scrape_runs(scrape_run_id),
    subject_hotel_id     INT NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    los                  SMALLINT NOT NULL,
    persons              SMALLINT NOT NULL,
    status               TEXT NOT NULL,
    duration_s           NUMERIC(10,2),
    rates_count          INT,
    months_scraped       TEXT[],
    error_message        TEXT,
    UNIQUE (scrape_run_id, subject_hotel_id, los, persons)
);
```

### 3.10 Forensic: `raw_payloads`

```sql
CREATE TABLE raw_payloads (
    payload_id           BIGSERIAL PRIMARY KEY,
    scrape_run_id        BIGINT NOT NULL REFERENCES scrape_runs(scrape_run_id),
    subject_hotel_id     INT NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    source_id            SMALLINT NOT NULL REFERENCES sources(source_id),
    los                  SMALLINT NOT NULL,
    persons              SMALLINT NOT NULL,
    scrape_date          DATE NOT NULL,
    payload              JSONB NOT NULL,
    payload_sha256       CHAR(64) NOT NULL,
    stored_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_to_cold     BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (scrape_run_id, subject_hotel_id, los, persons)
);

CREATE INDEX idx_raw_scrape_date ON raw_payloads (scrape_date) WHERE archived_to_cold = FALSE;
```

---

## 4. Ingest flow

For each Lighthouse JSON file (one file = one subject hotel × one source × one scrape date):

1. Insert `raw_payloads` (idempotent on `payload_sha256`).
2. Upsert `scrape_runs` + `scrape_run_hotels`.
3. Upsert `hotels` for subject + every competitor in the file. Since `external_hotel_id` is unique, brand.com's file for the same subject will find existing rows from booking.com's file and just bump `last_seen_at`.
4. Upsert `compset_members` (add new competitors, close out removed ones).
5. For each rate cell × competitor × LOS:
   - Look up prior row in `rates_current` by natural key.
   - INSERT into `rate_observations` with `prior_rate_value`, `rate_delta`, `changed_from_prior`.
   - UPSERT `rates_current`.

**Important ingest behavior:** When the booking.com JSON arrives at 9:00 AM and the brand.com JSON arrives at 9:15 AM for the same subject on the same day, they both process independently. Each creates its own `rate_observations` rows (different `source_id`), each updates its own `rates_current` row. The `hotels` table is shared — whichever ran first created the competitor rows; the second one just updates `last_seen_at`.

---

## 5. Sizing (3 years hot)

- 10 subjects × ~10 competitors = 100 compset pairs
- × 90 forward stay dates, scraped daily = 9,000 cells/day per (source × LOS)
- × 3 LOS variants = 27,000
- × 2 sources = 54,000
- × 365 days = **~20M observations/year**
- × 3 years = **~60M rows**

Adding a third source later: ~90M rows. Fine for PostgreSQL with monthly partitioning. ~25–35 GB on disk including indexes.

`raw_payloads`: ~22,000 files/year × ~400 KB = ~9 GB/year hot. Archive to S3 after 90 days to keep hot footprint at ~2 GB.

---

## 6. The 5/1 → 5/2 example

**5/1, 9:00 AM** — booking.com scrape runs. For subject=ESA Lakeline, competitor=Motel 6 Cedar Park (`external_hotel_id=2022277`, `hotel_pk=7`), stay_date=5/7, LOS=7, persons=2:
- `rate_observations`: new row with `source_id=1 (booking)`, `rate_value=89.00`, `prior_rate_value=NULL`, `changed_from_prior=TRUE`, `observation_date=5/1`.
- `rates_current`: new row.

**5/1, 9:15 AM** — brand.com scrape runs. Same subject, same competitor, same stay_date/LOS/persons:
- `rate_observations`: new row with `source_id=2 (brand)`, `rate_value=82.00`, `prior_rate_value=NULL`, `changed_from_prior=TRUE`, `observation_date=5/1`.
- `rates_current`: new row (different `source_id`, different unique key).
- `hotels[hotel_pk=7].last_seen_at` → bumped to 9:15. No duplicate row created.

**5/2, 9:00 AM** — booking.com scrape. Same key, rate still $89:
- `rate_observations`: new row with `rate_value=89.00`, `prior_rate_value=89.00`, `rate_delta=0`, `changed_from_prior=FALSE`, `observation_date=5/2`.
- `rates_current`: `last_scraped_at=5/2 09:00`, everything else unchanged.

**5/2, 9:15 AM** — brand.com scrape. Same key, rate dropped to $79:
- `rate_observations`: new row with `source_id=2`, `rate_value=79.00`, `prior_rate_value=82.00`, `rate_delta=-3.00`, `changed_from_prior=TRUE`, `observation_date=5/2`.
- `rates_current`: `rate_value=79.00`, `last_changed_at=5/2 09:15`.

You now have 4 observation rows describing two sources × two days for the same competitor/stay_date. Plotting the booking curve for 5/7 just filters by stay_date and orders by observation_date — and you can split the line by source.

---

## 7. Metabase views

```sql
-- Latest rate per key
CREATE VIEW v_rates_latest AS
SELECT rc.*, s.source_code, sh.display_name AS subject_name,
       h.name AS competitor_name, h.stars AS competitor_stars
FROM rates_current rc
JOIN sources s          ON s.source_id = rc.source_id
JOIN subject_hotels sh  ON sh.subject_hotel_id = rc.subject_hotel_id
JOIN hotels h           ON h.hotel_pk = rc.competitor_hotel_pk;

-- Daily rate time series (booking curve)
CREATE VIEW v_rate_trend AS
SELECT ro.observation_date, ro.stay_date, ro.leadtime_days,
       s.source_code, sh.display_name AS subject_name,
       h.name AS competitor_name,
       ro.los, ro.persons,
       ro.rate_value, ro.all_in_price, ro.rate_delta,
       ro.is_available
FROM rate_observations ro
JOIN sources s         ON s.source_id = ro.source_id
JOIN subject_hotels sh ON sh.subject_hotel_id = ro.subject_hotel_id
JOIN hotels h          ON h.hotel_pk = ro.competitor_hotel_pk;

-- Subject vs. compset median, per stay_date × observation_date × source × LOS
CREATE VIEW v_subject_vs_compset AS
WITH own AS (
    SELECT ro.source_id, ro.subject_hotel_id, ro.stay_date, ro.los, ro.persons,
           ro.observation_date, ro.rate_value AS own_rate, ro.all_in_price AS own_all_in
    FROM rate_observations ro
    JOIN subject_hotels sh
      ON sh.subject_hotel_id = ro.subject_hotel_id
     AND sh.hotel_pk = ro.competitor_hotel_pk
),
comp AS (
    SELECT ro.source_id, ro.subject_hotel_id, ro.stay_date, ro.los, ro.persons, ro.observation_date,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ro.rate_value) AS median_rate,
           AVG(ro.rate_value)        AS avg_rate,
           MIN(ro.rate_value)        AS min_rate,
           MAX(ro.rate_value)        AS max_rate,
           COUNT(*)                  AS compset_size
    FROM rate_observations ro
    JOIN subject_hotels sh
      ON sh.subject_hotel_id = ro.subject_hotel_id
     AND sh.hotel_pk <> ro.competitor_hotel_pk
    GROUP BY ro.source_id, ro.subject_hotel_id, ro.stay_date, ro.los, ro.persons, ro.observation_date
)
SELECT o.*, c.median_rate, c.avg_rate, c.min_rate, c.max_rate, c.compset_size,
       o.own_rate - c.median_rate AS delta_vs_median
FROM own o
JOIN comp c USING (source_id, subject_hotel_id, stay_date, los, persons, observation_date);

-- Cross-source: booking vs. brand for the same hotel × stay_date × observation_date
-- Works for subject's own rate AND for any competitor in the compset
CREATE VIEW v_source_comparison AS
SELECT
    h.name AS hotel_name,
    h.external_hotel_id,
    ro.stay_date, ro.los, ro.persons, ro.observation_date,
    MAX(CASE WHEN s.source_code='booking' THEN ro.rate_value   END) AS booking_rate,
    MAX(CASE WHEN s.source_code='brand'   THEN ro.rate_value   END) AS brand_rate,
    MAX(CASE WHEN s.source_code='booking' THEN ro.all_in_price END) AS booking_all_in,
    MAX(CASE WHEN s.source_code='brand'   THEN ro.all_in_price END) AS brand_all_in,
    MAX(CASE WHEN s.source_code='brand'   THEN ro.all_in_price END) -
    MAX(CASE WHEN s.source_code='booking' THEN ro.all_in_price END) AS brand_minus_booking
FROM rate_observations ro
JOIN sources s ON s.source_id = ro.source_id
JOIN hotels h  ON h.hotel_pk  = ro.competitor_hotel_pk
GROUP BY h.name, h.external_hotel_id, ro.stay_date, ro.los, ro.persons, ro.observation_date;
```

---

## 8. Day 1 vs. day 30

**Day 1 (MVP):**
- All dimension tables (`sources`, `hotels`, `subject_hotels`, `compset_members`, `stay_parameters`).
- `rates_current`, `rate_observations` with 3 months of partitions.
- `scrape_runs` / `scrape_run_hotels` / `raw_payloads`.
- Ingest script for Lighthouse JSON.
- Views: `v_rates_latest`, `v_rate_trend`, `v_subject_vs_compset`.

**Day 30 (after brand.com data arrives):**
- `rate_changes` materialized view + nightly refresh.
- `v_source_comparison`.
- S3 cold-tier archival for `raw_payloads` > 90 days.
- `pg_partman` automation.
- Alert queries: "price moved >15% overnight", "competitor went unavailable", "brand.com rate diverged from booking.com by >$X".

---

## 9. Open items

1. **Multiple scrapes per day.** Current key uses `observation_date` (DATE). If you ever scrape twice a day, change the unique key to include `observation_ts` and add a `scrape_slot` or similar.
2. **Compset drift.** When a competitor drops out of a Lighthouse compset, close the `compset_members` row (`valid_to = today`). Don't delete it — you want history to remain interpretable.
3. **Rate parity alerts.** Once brand.com data is flowing, the high-value dashboard is "where is brand.com cheaper/more expensive than booking.com for our own hotels." `v_source_comparison` answers this directly; consider a daily email of outliers.
