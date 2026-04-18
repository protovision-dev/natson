-- Helper used by the Metabase rate-grid SQL to keep column headers
-- short.  22 chars + ellipsis is narrow enough to let Metabase fit
-- 8-11 compset columns + subject + market-demand across the viewport
-- without horizontal scroll.  Full name remains in the underlying
-- hotels.name and shows on hover.

CREATE OR REPLACE FUNCTION _trim_name(name TEXT, max_len INT DEFAULT 22)
RETURNS TEXT AS $$
    SELECT CASE
        WHEN name IS NULL                THEN NULL
        WHEN length(name) <= max_len     THEN name
        ELSE substr(name, 1, max_len - 1) || '…'
    END;
$$ LANGUAGE sql IMMUTABLE;
