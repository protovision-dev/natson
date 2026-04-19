"""Discovery: load the rates page, find the Refresh button, click it,
and capture every XHR that fires to identify the refresh API endpoint.

Run once. Output goes to stdout + output/refresh_discovery.json.
"""

import json
import os
import sys
from pathlib import Path

import requests

API = os.environ.get("BROWSER_API", "http://localhost:8765")
OUT = Path("output")
SESSION = json.loads((OUT / "session.json").read_text())
PAGE = "https://app.mylighthouse.com/hotel/345062/rates?compsetId=1&los=7&maxPersons=2&month=2026-04&view=table"

cookies = [
    {
        "name": c["name"],
        "value": c["value"],
        "domain": "app.mylighthouse.com",
        "path": "/",
        "secure": True,
        "sameSite": "None",
    }
    for c in SESSION["cookies"]
]

# Step 1: Load the page and find the Refresh button.
# Use /login which supports steps (click, waitForSelector, etc.)
payload = {
    "url": PAGE,
    "viewport": {"width": 1600, "height": 1100},
    "initialWaitUntil": "networkidle",
    "steps": [
        # Wait for the page to render (rates grid should appear).
        {"action": "waitForTimeout", "ms": 5000},
    ],
    # Pre-seed auth cookies so we land on the real page.
    "cookieDomains": ["app.mylighthouse.com"],
    # Capture ALL XHRs from page load (before clicking Refresh) to establish a baseline.
    "captureXhrUrlContains": ["/api/", "/apigateway/"],
}

# But /login doesn't accept cookies to pre-seed the context...
# We need to add that capability or use a different approach.
# Actually, let's use /scrape first to get the rendered page + find the button,
# then use /login with steps for the click.

# ---- Phase A: Render the page, find the refresh button ----
print("[*] Phase A: loading rates page to find Refresh button...")
r = requests.post(
    f"{API}/scrape",
    json={
        "url": PAGE,
        "waitFor": 8000,
        "timeout": 90000,
        "cookies": cookies,
        "captureXhrUrlContains": ["/api/", "/apigateway/"],
    },
    timeout=180,
)
resp = r.json()
if not resp.get("success"):
    print(f"[!] scrape failed: {resp.get('error')}")
    sys.exit(1)

html = resp["data"]["rawHtml"]
baseline_xhrs = resp["data"].get("xhrs", [])
print(f"    HTML: {len(html):,} B, baseline XHRs: {len(baseline_xhrs)}")

# Search the DOM for refresh-related elements.
import re  # noqa: E402  (imported here to keep the script's flow readable)

# Look for buttons/links with "refresh" in text, class, or data attributes.
refresh_candidates = re.findall(
    r"<(?:button|a|div|span)[^>]*(?:refresh|Refresh|resync|Resync|update|Update)[^>]*>", html, re.I
)
print(f"    refresh-looking elements in HTML: {len(refresh_candidates)}")
for c in refresh_candidates[:10]:
    print(f"      {c[:200]}")

# Also look for specific data-event-id or data-testid attributes.
data_attrs = re.findall(
    r'data-(?:event-id|testid|action)="[^"]*(?:refresh|update|resync)[^"]*"', html, re.I
)
print(f"    data-* attrs with refresh/update: {data_attrs[:10]}")

# Look for liveupdates response in baseline XHRs.
for x in baseline_xhrs:
    if "liveupdates" in x["url"]:
        print(f"\n    liveupdates baseline: {x['body'][:500]}")

# ---- Phase B: Click the button and capture XHRs ----
# We need to add cookies to /login. Let me check if server supports it...
# Looking at server.py /login: it doesn't accept pre-seeded cookies.
# Workaround: add cookies via steps (goto to set domain, then add cookies via JS).
# Better: extend /login to accept cookies. But for discovery, let me use a
# different approach: find the refresh API endpoint by inspecting the JS bundle,
# or try known candidates.

# ---- Phase C: Try likely refresh API endpoints directly ----
print("\n[*] Phase C: probing likely refresh API endpoints...")
sess = requests.Session()
for c in SESSION["cookies"]:
    sess.cookies.set(c["name"], c["value"], domain=c["domain"])
sess.headers.update(
    {
        "User-Agent": SESSION["user_agent"],
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://app.mylighthouse.com",
        "Referer": PAGE,
        "X-CSRFToken": next(
            (c["value"] for c in SESSION["cookies"] if c["name"] == "csrftoken"), ""
        ),
    }
)

probes = [
    ("POST", "/api/v3/shops/", {"hotel_id": 345062}),
    ("POST", "/api/v3/shops/", {"hotel_id": "345062"}),
    ("POST", "/api/v3/liveupdates/", {"hotel_id": 345062}),
    ("PUT", "/api/v3/liveupdates/", {"hotel_id": 345062}),
    ("POST", "/apigateway/v1/app/rates/refresh/", {"hotel_id": "345062"}),
    ("POST", "/apigateway/v1/app/refresh/", {"hotel_id": "345062", "compset_ids": [1]}),
    ("POST", "/api/v3/hotels/345062/refresh/", {}),
    ("PUT", "/api/v3/hotels/345062/refresh/", {}),
    ("POST", "/api/v3/hotels/345062/resync/", {}),
    ("POST", "/apigateway/v1/app/resync/", {"hotel_id": "345062"}),
    ("POST", "/api/v3/shops/create/", {"hotel_id": "345062"}),
    ("POST", "/api/v3/shops/trigger/", {"hotel_id": "345062"}),
    ("POST", "/apigateway/v1/app/shops/", {"hotel_id": "345062"}),
    (
        "POST",
        "/apigateway/v1/app/shops/trigger/",
        {"hotel_id": "345062", "subscription_id": "345062"},
    ),
]

for method, path, body in probes:
    try:
        r = sess.request(method, f"https://app.mylighthouse.com{path}", json=body, timeout=15)
    except Exception as e:
        print(f"  {method:4} {path:<50}  ERR {e}")
        continue
    ct = r.headers.get("content-type", "")
    preview = (
        r.text[:200] if "json" in ct or len(r.text) < 500 else f"<{ct} {len(r.text)}B>"
    ).replace("\n", " ")
    interesting = r.status_code in (200, 201, 202, 204)
    marker = "★" if interesting else " "
    print(f"  {marker} {method:4} {path:<50}  HTTP {r.status_code}  {preview[:150]}")

# Save everything for later reference.
(OUT / "refresh_discovery.json").write_text(
    json.dumps(
        {
            "baseline_xhrs": [
                {"url": x["url"], "status": x["status"], "method": x["method"]}
                for x in baseline_xhrs
            ],
            "refresh_candidates_html": refresh_candidates[:20],
            "data_attrs": data_attrs[:20],
            "probes": [{"method": m, "path": p, "body": b} for m, p, b in probes],
        },
        indent=2,
    )
)
print(f"\n[*] saved to {OUT / 'refresh_discovery.json'}")
