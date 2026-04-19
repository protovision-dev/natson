"""Example: log into MyLighthouse via browser-api and print the session cookies.

Run with:
  LH_USER=you@example.com LH_PASS='...' python lighthouse_login.py
"""

import json
import os
import sys

import requests

API = os.environ.get("BROWSER_API", "http://localhost:8765")
USERNAME = os.environ["LH_USER"]
PASSWORD = os.environ["LH_PASS"]

payload = {
    "url": "https://app.mylighthouse.com/",
    "viewport": {"width": 1440, "height": 900},
    "initialWaitUntil": "networkidle",
    "steps": [
        {"action": "waitForSelector", "selector": "input[type=email]", "timeout": 30000},
        {"action": "fill", "selector": "input[type=email]", "value": USERNAME},
        {"action": "press", "selector": "input[type=email]", "key": "Enter"},
        {"action": "waitForSelector", "selector": "input[type=password]", "timeout": 15000},
        {"action": "fill", "selector": "input[type=password]", "value": PASSWORD},
        {"action": "click", "selector": "button[type=submit], button:has-text('Log in')"},
        # Wait for the first authenticated call to succeed — this is the "I'm logged in" signal.
        {
            "action": "waitForResponse",
            "urlContains": "/api/v3/users/?only_self=true",
            "status": 200,
            "timeout": 45000,
        },
    ],
    "cookieDomains": ["app.mylighthouse.com"],
    "cookieNames": ["sessionid", "csrftoken"],
}

r = requests.post(f"{API}/login", json=payload, timeout=180)
r.raise_for_status()
resp = r.json()
if not resp.get("success"):
    print(f"login failed: {resp.get('error')}", file=sys.stderr)
    sys.exit(1)

print(f"finalUrl: {resp['finalUrl']}")
print(f"cookies:  {[c['name'] for c in resp['cookies']]}")
print(json.dumps(resp, indent=2))
