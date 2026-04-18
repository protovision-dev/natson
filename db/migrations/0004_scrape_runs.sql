-- Scrape audit trail (schema v3 §3.9) + raw payloads (§3.10).
-- scrape_runs here ≠ scrape_jobs (Phase 3 table).  scrape_jobs tracks
-- JOB state for dashboards; scrape_runs is the ingest/audit link
-- between a scrape_job and the rate_observations rows it produced.
-- Multiple concurrent jobs on the same (source, scrape_date) each get
-- their own scrape_runs row — disambiguated by scrape_job_id.

-- -----------------------------------------------------------------------
-- scrape_runs: one row per Job per ingest execution.
-- Key: (source_id, scrape_date, scrape_job_id) — concurrent-safe.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_runs (
    scrape_run_id    BIGSERIAL   PRIMARY KEY,
    source_id        SMALLINT    NOT NULL REFERENCES sources(source_id),
    scrape_date      DATE        NOT NULL,
    scrape_job_id    TEXT        REFERENCES scrape_jobs(job_id) ON DELETE SET NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    completed_at     TIMESTAMPTZ,
    hotels_scraped   INT,
    hotels_failed    INT,
    status           TEXT        NOT NULL DEFAULT 'running',
    notes            TEXT,
    UNIQUE (source_id, scrape_date, scrape_job_id)
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_source_date
    ON scrape_runs (source_id, scrape_date DESC);

-- -----------------------------------------------------------------------
-- scrape_run_hotels: one row per (subject, los, persons) within a run.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_run_hotels (
    scrape_run_hotel_id  BIGSERIAL   PRIMARY KEY,
    scrape_run_id        BIGINT      NOT NULL REFERENCES scrape_runs(scrape_run_id) ON DELETE CASCADE,
    subject_hotel_id     INT         NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    los                  SMALLINT    NOT NULL,
    persons              SMALLINT    NOT NULL,
    status               TEXT        NOT NULL,
    duration_s           NUMERIC(10,2),
    rates_count          INT,
    months_scraped       TEXT[],
    error_message        TEXT,
    UNIQUE (scrape_run_id, subject_hotel_id, los, persons)
);

-- -----------------------------------------------------------------------
-- raw_payloads: forensic copy of the snapshot dict we wrote to disk.
-- Idempotent upsert on natural key (one payload per run/subject/LOS/persons).
-- 90-day retention is enforced elsewhere (cold archival — future phase).
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_payloads (
    payload_id        BIGSERIAL   PRIMARY KEY,
    scrape_run_id     BIGINT      NOT NULL REFERENCES scrape_runs(scrape_run_id) ON DELETE CASCADE,
    subject_hotel_id  INT         NOT NULL REFERENCES subject_hotels(subject_hotel_id),
    source_id         SMALLINT    NOT NULL REFERENCES sources(source_id),
    los               SMALLINT    NOT NULL,
    persons           SMALLINT    NOT NULL,
    scrape_date       DATE        NOT NULL,
    payload           JSONB       NOT NULL,
    payload_sha256    CHAR(64)    NOT NULL,
    stored_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_to_cold  BOOLEAN     NOT NULL DEFAULT FALSE,
    UNIQUE (scrape_run_id, subject_hotel_id, los, persons)
);

CREATE INDEX IF NOT EXISTS idx_raw_scrape_date
    ON raw_payloads (scrape_date)
    WHERE archived_to_cold = FALSE;
