-- Seed subject_hotels from scraper/subject_hotels.json.
--
-- The JSON is the source of truth for portfolio metadata (internal_code,
-- display_name, brand, etc.).  This migration inserts a stub `hotels`
-- row for each subject (name = display_name, external_hotel_id =
-- hotel_id from scraper/hotels.json), then a subject_hotels row that
-- links back.
--
-- Ingest (5.5) will overwrite the stub `hotels.name`/metadata with
-- whatever the scrape payload reports — the Lighthouse name for a
-- subject is usually richer than our display_name.
--
-- Idempotent via ON CONFLICT clauses.

-- Subjects --------------------------------------------------------------
WITH subject_seed(external_hotel_id, internal_code, display_name,
                  city, state, country, brand, lighthouse_compset_id) AS (
    VALUES
      ('345062', 'ESA-AUS-LAKE',  'ESA Austin Lakeline',
          'Austin',          'TX', 'US', 'Extended Stay America', 1),
      ('345069', 'ESA-CLW-CARL',  'ESA Clearwater Carillon',
          'Clearwater',      'FL', 'US', 'Extended Stay America', 1),
      ('344406', 'HTS-ATL-LAWR',  'HomeTowne Studios Atlanta Lawrenceville',
          'Lawrenceville',   'GA', 'US', 'HomeTowne Studios',     1),
      ('276780', 'M6-ORL-INTL',   'Motel 6 Orlando International Dr',
          'Orlando',         'FL', 'US', 'Motel 6',               1),
      ('276782', 'M6-ORL-WPAR',   'Motel 6 Orlando Winter Park',
          'Orlando',         'FL', 'US', 'Motel 6',               1),
      ('276792', 'S6-AUS-MID',    'Studio 6 Austin Midtown',
          'Austin',          'TX', 'US', 'Studio 6',              1),
      ('276784', 'S6-GSO',        'Studio 6 Greensboro',
          'Greensboro',      'NC', 'US', 'Studio 6',              1),
      ('303035', 'S6-ATL-ROSW',   'Studio 6 Atlanta Roswell',
          'Roswell',         'GA', 'US', 'Studio 6',              1),
      ('273870', 'S6-RIC-I64W',   'Studio 6 Richmond I-64 West',
          'Richmond',        'VA', 'US', 'Studio 6',              1),
      ('273872', 'S6-WPB',        'Studio 6 West Palm Beach',
          'West Palm Beach', 'FL', 'US', 'Studio 6',              1)
),
upsert_hotels AS (
    INSERT INTO hotels (external_hotel_id, name, country)
    SELECT external_hotel_id, display_name, country
    FROM subject_seed
    ON CONFLICT (external_hotel_id) DO UPDATE
        SET last_seen_at = NOW()
    RETURNING hotel_pk, external_hotel_id
)
INSERT INTO subject_hotels
    (hotel_pk, internal_code, display_name, city, state, country,
     brand, lighthouse_compset_id)
SELECT uh.hotel_pk, ss.internal_code, ss.display_name, ss.city, ss.state,
       ss.country, ss.brand, ss.lighthouse_compset_id
FROM subject_seed ss
JOIN upsert_hotels uh USING (external_hotel_id)
ON CONFLICT (hotel_pk) DO UPDATE
    SET internal_code          = EXCLUDED.internal_code,
        display_name           = EXCLUDED.display_name,
        city                   = EXCLUDED.city,
        state                  = EXCLUDED.state,
        country                = EXCLUDED.country,
        brand                  = EXCLUDED.brand,
        lighthouse_compset_id  = EXCLUDED.lighthouse_compset_id;
