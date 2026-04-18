# Booking.com scraping — parked

These scripts scrape Booking.com directly to cross-check Lighthouse's
`shop_value` against the real OTA page price. They're parked here while
the main focus is on improving the Lighthouse pipeline.

## Scripts

- `booking_direct.py` — scrape via browser-api + Smartproxy residential proxy
- `firecrawl_may.py` — scrape via Firecrawl API (paid, handles bot detection)
- `firecrawl_test.py` — small-batch Firecrawl test (10 URLs)
- `probe_compset_search.py` — one-off Lighthouse compset search exploration
- `discover_refresh.py` — one-off discovery of the Lighthouse Refresh button

## To re-activate

Move scripts back to `scraper/`, ensure `smartproxy.txt` and `firecrawl.txt`
are up to date, and re-enable the proxy in `browser-api/compose.yaml`.
