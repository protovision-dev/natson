-- v_rate_grid_latest: per (subject, source, stay_date, competitor, los, persons),
-- return the latest rate observation we have.  Feeds the Lighthouse-style
-- rate grid dashboards (one row per stay_date × one column per competitor).
-- Also surfaces market_demand_pct + an is_own flag so the subject's own
-- rate can be stacked first in the grid.

CREATE OR REPLACE VIEW v_rate_grid_latest AS
WITH latest AS (
    SELECT source_id, subject_hotel_id, competitor_hotel_pk,
           stay_date, los, persons,
           MAX(observation_date) AS latest_observation_date
    FROM rate_observations
    GROUP BY 1, 2, 3, 4, 5, 6
)
SELECT
    s.source_code,
    sh.internal_code    AS subject_code,
    sh.display_name     AS subject_name,
    ro.stay_date,
    ro.los,
    ro.persons,
    h.external_hotel_id AS competitor_hotelinfo_id,
    h.name              AS competitor_name,
    (ro.competitor_hotel_pk = sh.hotel_pk) AS is_own,
    ro.rate_value,
    ro.shop_value,
    ro.all_in_price,
    ro.market_demand_pct,
    ro.is_available,
    ro.message,
    ro.observation_date
FROM rate_observations ro
JOIN latest l
  ON  l.source_id           = ro.source_id
  AND l.subject_hotel_id    = ro.subject_hotel_id
  AND l.competitor_hotel_pk = ro.competitor_hotel_pk
  AND l.stay_date           = ro.stay_date
  AND l.los                 = ro.los
  AND l.persons             = ro.persons
  AND l.latest_observation_date = ro.observation_date
JOIN sources s          ON s.source_id         = ro.source_id
JOIN subject_hotels sh  ON sh.subject_hotel_id = ro.subject_hotel_id
JOIN hotels h           ON h.hotel_pk          = ro.competitor_hotel_pk;
