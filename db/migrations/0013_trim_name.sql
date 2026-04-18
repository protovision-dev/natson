-- Helper used by the Metabase rate-grid SQL to keep column headers
-- short.  Metabase sizes columns to fit the HEADER TEXT (not the cell
-- values) on pivoted tables, so a tight cap is the real lever to fit
-- more competitors across the viewport.
--
-- Head-and-tail truncation is CRITICAL: plain head truncation collapses
-- hotels whose names share a long common prefix (e.g. three
-- "Extended Stay America Suites - …" competitors all become "Extended …",
-- merging their pivot columns into one).  Keeping the last 8 chars
-- preserves the distinguishing suffix ("…ine Mall", "…rboretum",
-- "…rch Park") so pivots stay unique.

CREATE OR REPLACE FUNCTION _trim_name(name TEXT, head INT DEFAULT 6, tail INT DEFAULT 8)
RETURNS TEXT AS $$
    SELECT CASE
        WHEN name IS NULL                          THEN NULL
        WHEN length(name) <= head + tail + 1       THEN name
        ELSE substr(name, 1, head) || '…'
             || substr(name, length(name) - tail + 1, tail)
    END;
$$ LANGUAGE sql IMMUTABLE;
