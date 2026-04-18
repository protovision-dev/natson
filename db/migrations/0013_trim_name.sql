-- Helper used by the Metabase rate-grid SQL to keep column headers
-- short.  Metabase sizes columns to fit the HEADER TEXT (not the cell
-- values) on pivoted tables, so a tight cap on header length is the
-- real lever to fit more competitors across the viewport.
-- 10 chars lets ~15 columns fit on a typical laptop without scroll.
-- Full name remains in hotels.name and shows on hover.

CREATE OR REPLACE FUNCTION _trim_name(name TEXT, max_len INT DEFAULT 10)
RETURNS TEXT AS $$
    SELECT CASE
        WHEN name IS NULL                THEN NULL
        WHEN length(name) <= max_len     THEN name
        ELSE substr(name, 1, max_len - 1) || '…'
    END;
$$ LANGUAGE sql IMMUTABLE;
