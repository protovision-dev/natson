"""Job abstraction for the Lighthouse scraper.

A Job is a fully-specified scrape invocation: which subscription hotels,
which check-in dates, what URL parameters (OTA/LOS/persons/…), and whether
to trigger a refresh.  Jobs are constructed from CLI flags or a JSON spec
file, run sequentially per (hotel, OTA) pair, and may run concurrently
across different (hotel, OTA) pairs guarded by fcntl locks.
"""
