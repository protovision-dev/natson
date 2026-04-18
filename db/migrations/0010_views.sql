-- Metabase-facing views on top of the fact tables.  Schema v3 §7.

CREATE OR REPLACE VIEW v_rates_latest AS
SELECT rc.*,
       s.source_code,
       sh.internal_code    AS subject_code,
       sh.display_name     AS subject_name,
       sh.brand            AS subject_brand,
       sh.city             AS subject_city,
       sh.state            AS subject_state,
       h.name              AS competitor_name,
       h.stars             AS competitor_stars,
       h.hotel_group       AS competitor_group,
       h.external_hotel_id AS competitor_hotelinfo_id
FROM rates_current rc
JOIN sources s          ON s.source_id = rc.source_id
JOIN subject_hotels sh  ON sh.subject_hotel_id = rc.subject_hotel_id
JOIN hotels h           ON h.hotel_pk = rc.competitor_hotel_pk;

-- -----------------------------------------------------------------------

CREATE OR REPLACE VIEW v_rate_trend AS
SELECT ro.observation_date,
       ro.observation_ts,
       ro.stay_date,
       ro.checkout_date,
       ro.leadtime_days,
       s.source_code,
       sh.internal_code  AS subject_code,
       sh.display_name   AS subject_name,
       sh.brand          AS subject_brand,
       h.name            AS competitor_name,
       h.external_hotel_id AS competitor_hotelinfo_id,
       ro.los,
       ro.persons,
       ro.rate_value,
       ro.all_in_price,
       ro.prior_rate_value,
       ro.rate_delta,
       ro.changed_from_prior,
       ro.is_available,
       ro.market_demand_pct
FROM rate_observations ro
JOIN sources s         ON s.source_id = ro.source_id
JOIN subject_hotels sh ON sh.subject_hotel_id = ro.subject_hotel_id
JOIN hotels h          ON h.hotel_pk = ro.competitor_hotel_pk;

-- -----------------------------------------------------------------------

CREATE OR REPLACE VIEW v_subject_vs_compset AS
WITH own AS (
    SELECT ro.source_id, ro.subject_hotel_id, ro.stay_date, ro.los, ro.persons,
           ro.observation_date,
           ro.rate_value    AS own_rate,
           ro.all_in_price  AS own_all_in
    FROM rate_observations ro
    JOIN subject_hotels sh ON sh.subject_hotel_id = ro.subject_hotel_id
    JOIN hotels h          ON h.hotel_pk = ro.competitor_hotel_pk
                           AND h.hotel_pk = sh.hotel_pk
),
comp AS (
    SELECT ro.source_id, ro.subject_hotel_id, ro.stay_date, ro.los,
           ro.persons, ro.observation_date,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ro.rate_value) AS median_rate,
           AVG(ro.rate_value)           AS avg_rate,
           MIN(ro.rate_value)           AS min_rate,
           MAX(ro.rate_value)           AS max_rate,
           COUNT(*)                     AS compset_size
    FROM rate_observations ro
    JOIN subject_hotels sh ON sh.subject_hotel_id = ro.subject_hotel_id
    WHERE ro.competitor_hotel_pk <> sh.hotel_pk
      AND ro.rate_value IS NOT NULL
    GROUP BY ro.source_id, ro.subject_hotel_id, ro.stay_date, ro.los,
             ro.persons, ro.observation_date
)
SELECT s.source_code,
       sh.internal_code  AS subject_code,
       sh.display_name   AS subject_name,
       o.stay_date, o.los, o.persons, o.observation_date,
       o.own_rate, o.own_all_in,
       c.median_rate, c.avg_rate, c.min_rate, c.max_rate, c.compset_size,
       o.own_rate - c.median_rate AS delta_vs_median
FROM own o
JOIN comp c           USING (source_id, subject_hotel_id, stay_date, los, persons, observation_date)
JOIN sources s        ON s.source_id = o.source_id
JOIN subject_hotels sh ON sh.subject_hotel_id = o.subject_hotel_id;
