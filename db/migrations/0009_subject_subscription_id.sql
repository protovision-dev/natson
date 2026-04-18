-- Correct the seed: hotels.external_hotel_id holds the Lighthouse
-- `hotelinfo_id` (the ID shared across OTAs), NOT the subscription_id.
-- The subscription_id is scraper-side-only (used to drive /rates and
-- /liveshop) so it belongs on subject_hotels as a separate column.
--
-- 0008 seeded external_hotel_id with subscription_ids — wrong.
-- Since no rate data exists yet, we can safely wipe the subject +
-- related `hotels` rows and re-seed with the correct mapping.

-- Add the scraper-side subscription_id.  Nullable first so the UPDATE
-- below can populate it; tightened to NOT NULL + UNIQUE after.
ALTER TABLE subject_hotels
    ADD COLUMN IF NOT EXISTS subscription_id TEXT;

-- Wipe the wrongly-seeded subjects + their stub hotel rows (cascade-safe:
-- no rate_observations or rates_current point at them yet).
DELETE FROM subject_hotels;
DELETE FROM hotels
    WHERE external_hotel_id IN (
        '345062','345069','344406','276780','276782',
        '276792','276784','303035','273870','273872'
    );

-- Re-seed correctly: external_hotel_id = hotelinfo_id (captured from
-- 2026-04-17 snapshots).  subscription_id = the hotels.json key.
WITH subject_seed(subscription_id, hotelinfo_id, internal_code, display_name,
                  city, state, country, brand, lighthouse_compset_id) AS (
    VALUES
      ('345062', '515836',  'ESA-AUS-LAKE',  'ESA Austin Lakeline',
          'Austin',          'TX', 'US', 'Extended Stay America', 1),
      ('345069', '518561',  'ESA-CLW-CARL',  'ESA Clearwater Carillon',
          'Clearwater',      'FL', 'US', 'Extended Stay America', 1),
      ('344406', '519010',  'HTS-ATL-LAWR',  'HomeTowne Studios Atlanta Lawrenceville',
          'Lawrenceville',   'GA', 'US', 'HomeTowne Studios',     1),
      ('276780', '47997',   'M6-ORL-INTL',   'Motel 6 Orlando International Dr',
          'Orlando',         'FL', 'US', 'Motel 6',               1),
      ('276782', '373927',  'M6-ORL-WPAR',   'Motel 6 Orlando Winter Park',
          'Orlando',         'FL', 'US', 'Motel 6',               1),
      ('276792', '1864485', 'S6-AUS-MID',    'Studio 6 Austin Midtown',
          'Austin',          'TX', 'US', 'Studio 6',              1),
      ('276784', '1920278', 'S6-GSO',        'Studio 6 Greensboro',
          'Greensboro',      'NC', 'US', 'Studio 6',              1),
      ('303035', '1985851', 'S6-ATL-ROSW',   'Studio 6 Atlanta Roswell',
          'Roswell',         'GA', 'US', 'Studio 6',              1),
      ('273870', '2760258', 'S6-RIC-I64W',   'Studio 6 Richmond I-64 West',
          'Richmond',        'VA', 'US', 'Studio 6',              1),
      ('273872', '1982616', 'S6-WPB',        'Studio 6 West Palm Beach',
          'West Palm Beach', 'FL', 'US', 'Studio 6',              1)
),
upsert_hotels AS (
    INSERT INTO hotels (external_hotel_id, name, country)
    SELECT hotelinfo_id, display_name, country
    FROM subject_seed
    ON CONFLICT (external_hotel_id) DO UPDATE
        SET last_seen_at = NOW()
    RETURNING hotel_pk, external_hotel_id
)
INSERT INTO subject_hotels
    (hotel_pk, subscription_id, internal_code, display_name, city, state,
     country, brand, lighthouse_compset_id)
SELECT uh.hotel_pk, ss.subscription_id, ss.internal_code, ss.display_name,
       ss.city, ss.state, ss.country, ss.brand, ss.lighthouse_compset_id
FROM subject_seed ss
JOIN upsert_hotels uh ON uh.external_hotel_id = ss.hotelinfo_id
ON CONFLICT (hotel_pk) DO UPDATE
    SET subscription_id      = EXCLUDED.subscription_id,
        internal_code         = EXCLUDED.internal_code,
        display_name          = EXCLUDED.display_name,
        city                  = EXCLUDED.city,
        state                 = EXCLUDED.state,
        country               = EXCLUDED.country,
        brand                 = EXCLUDED.brand,
        lighthouse_compset_id = EXCLUDED.lighthouse_compset_id;

-- Lock in the invariant: every subject_hotels row has a subscription_id.
ALTER TABLE subject_hotels
    ALTER COLUMN subscription_id SET NOT NULL;

-- Two unique constraints now:
--   (hotel_pk)         — already set in 0003
--   (subscription_id)  — new, for ingest lookup from scraper/hotels.json
ALTER TABLE subject_hotels
    ADD CONSTRAINT subject_hotels_subscription_id_unique UNIQUE (subscription_id);
