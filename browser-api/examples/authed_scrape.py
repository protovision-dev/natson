"""Example: load an authenticated page with cookies from a prior /login.

Combine with lighthouse_login.py to fetch a page that requires the SPA to
hydrate, then hand the rendered HTML off for parsing.
"""

import json
import os
import sys

import requests

API = os.environ.get("BROWSER_API", "http://localhost:8765")

if len(sys.argv) != 3:
    print("usage: authed_scrape.py <session.json> <url>", file=sys.stderr)
    sys.exit(2)

with open(sys.argv[1]) as _f:
    sess = json.loads(_f.read())
url = sys.argv[2]

payload = {
    "url": url,
    "waitFor": 4000,
    "cookies": [
        {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": "/"}
        for c in sess["cookies"]
    ],
    # Capture any JSON responses triggered during render so we can inspect them.
    "captureXhrUrlContains": ["/api/", "/apigateway/"],
}
r = requests.post(f"{API}/scrape", json=payload, timeout=240)
r.raise_for_status()
resp = r.json()
if not resp.get("success"):
    print(resp, file=sys.stderr)
    sys.exit(1)

data = resp["data"]
print(f"finalUrl: {data['finalUrl']}")
print(f"html size: {len(data['rawHtml'])} bytes")
print(f"xhrs: {len(data.get('xhrs') or [])}")
for x in data.get("xhrs") or []:
    print(f"  {x['status']} {x['method']} {x['url'][:140]}")
