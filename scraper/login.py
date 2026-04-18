"""Log into MyLighthouse via the local browser-api and save a reusable cookie jar.

Requires the browser-api service to be running — from repo root:
  cd browser-api && docker compose up -d
"""
import json
import os
import sys
from pathlib import Path

import requests

API = os.environ.get("BROWSER_API", "http://localhost:8765")
OUT = Path(os.environ.get("OUT_DIR", "output")) / "session.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

USERNAME = os.environ["LH_USER"]
PASSWORD = os.environ["LH_PASS"]

payload = {
    "url": "https://app.mylighthouse.com/",
    "viewport": {"width": 1440, "height": 900},
    "initialWaitUntil": "networkidle",
    "steps": [
        {"action": "waitForSelector", "selector": "input[type=email]", "timeout": 30000},
        {"action": "fill",  "selector": "input[type=email]", "value": USERNAME},
        {"action": "press", "selector": "input[type=email]", "key": "Enter"},
        {"action": "waitForSelector", "selector": "input[type=password]", "timeout": 15000},
        {"action": "fill",  "selector": "input[type=password]", "value": PASSWORD},
        {"action": "press", "selector": "input[type=password]", "key": "Enter"},
        {"action": "waitForResponse", "urlContains": "/api/v3/users/?only_self=true",
         "status": 200, "timeout": 45000},
    ],
    "cookieDomains": ["app.mylighthouse.com"],
    "cookieNames": ["sessionid", "csrftoken"],
}

r = requests.post(f"{API}/login", json=payload, timeout=180)
r.raise_for_status()
resp = r.json()
if not resp.get("success"):
    print(f"[!] login failed: {resp.get('error')}", file=sys.stderr)
    sys.exit(1)

OUT.write_text(json.dumps({
    "user_agent": resp["userAgent"],
    "cookies": [
        {"name": c["name"], "value": c["value"], "domain": c["domain"]}
        for c in resp["cookies"]
    ],
}, indent=2))
print(f"[*] wrote {OUT} ({[c['name'] for c in resp['cookies']]}) — finalUrl={resp['finalUrl']}")
