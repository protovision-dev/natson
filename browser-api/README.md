# browser-api

A long-running local HTTP service that wraps **Camoufox** (patched Firefox with
fingerprint spoofing). It replaces the "spin up a Docker container for every
camoufox call" pattern with a single always-on browser and cheap HTTP requests.

Three endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Is the browser ready? |
| `POST /scrape` | Navigate to a URL, return rendered HTML (+ optional XHR capture). |
| `POST /login` | Run a scripted login flow (fill/click/wait), return cookies. |
| `POST /api` | Issue an authenticated HTTP request *from inside* the browser context. |

---

## Running

```bash
cd browser-api
docker compose up -d --build
curl http://localhost:8765/health
# {"ok":true,"browser":true,"default_user_agent":"Mozilla/5.0 ..."}
```

First build pulls the Camoufox Firefox build (~700 MB) — goes once, then cached
in the image layer. Subsequent `up -d` is ~2 s.

To stop: `docker compose down`. To tail logs: `docker compose logs -f`.

### Configuration

Env vars (all optional):

| Var | Default | Meaning |
|---|---|---|
| `MAX_CONCURRENCY` | `4` | Semaphore cap. Each request holds one slot while its browser context is open. |
| `DEFAULT_UA` | Firefox 140 on Mac | Both the HTTP UA header and `navigator.userAgent` JS override. |
| `DEFAULT_OS` | `macos` | Camoufox OS fingerprint (windows / macos / linux). |
| `DEFAULT_LOCALE` | `en-US` | Browser locale. |

The UA matters: some sites (Lighthouse / MyLighthouse, e.g.) browser-sniff via
JS and redirect old versions to `/not_supported/`. Keep this UA current.

---

## Endpoints

### `GET /health`

```json
{"ok": true, "browser": true, "default_user_agent": "Mozilla/5.0 ..."}
```

### `POST /scrape`

Navigates a URL and returns the rendered DOM. Everything beyond `url` is
optional.

**Request:**
```json
{
  "url": "https://example.com/",
  "waitFor": 2000,                 // extra ms to idle after DOMContentLoaded
  "timeout": 60000,                // page.goto timeout (ms)
  "userAgent": null,               // override DEFAULT_UA
  "viewport": {"width": 1440, "height": 900},
  "cookies": [                     // pre-seed an authenticated session
    {"name": "sessionid", "value": "…", "domain": "example.com", "path": "/"}
  ],
  "scrollToBottom": false,         // scroll virtual lists until stable
  "stabilitySelector": null,       // count this to detect scroll-idle
  "scrollMaxIterations": 40,
  "scrollStepDelayMs": 600,
  "captureXhrUrlContains": null    // e.g. ["/api/", "/graphql"] → returns bodies
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "rawHtml": "<!doctype html>…",
    "finalUrl": "https://example.com/redirected-here",
    "xhrs": [                      // only when captureXhrUrlContains is set
      {"url": "…", "status": 200, "method": "GET", "body": "{…}"}
    ]
  }
}
```

### `POST /login`

Declarative multi-step flow. The browser navigates to `url`, then runs each
step in order. Returns cookies (optionally filtered).

**Request:**
```json
{
  "url": "https://app.example.com/",
  "userAgent": null,
  "viewport": {"width": 1440, "height": 900},
  "initialWaitUntil": "networkidle",  // or "domcontentloaded" / "load"
  "steps": [
    {"action": "waitForSelector", "selector": "input[type=email]", "timeout": 30000},
    {"action": "fill",  "selector": "input[type=email]", "value": "user@x.com"},
    {"action": "press", "selector": "input[type=email]", "key": "Enter"},
    {"action": "waitForSelector", "selector": "input[type=password]", "timeout": 15000},
    {"action": "fill",  "selector": "input[type=password]", "value": "hunter2"},
    {"action": "click", "selector": "button[type=submit]"},
    {"action": "waitForResponse", "urlContains": "/api/me", "status": 200, "timeout": 45000}
  ],
  "cookieDomains": ["app.example.com"],   // optional whitelist
  "cookieNames": ["sessionid", "csrftoken"],  // optional whitelist
  "captureXhrUrlContains": null           // e.g. ["/api/"] for API discovery
}
```

**Step actions:**

| `action` | Required fields | Notes |
|---|---|---|
| `goto` | `url` | Navigate mid-flow. Waits for `domcontentloaded`. |
| `fill` | `selector`, `value` | Types into an input. |
| `press` | `selector`, `key` | Sends a keypress (e.g. `"Enter"`). |
| `click` | `selector` | CSS selectors; `has-text()` supported. |
| `waitForSelector` | `selector` | Until element is visible. |
| `waitForURL` | `url` or `urlContains` | Until the page URL matches. |
| `waitForResponse` | `urlContains`, optional `status` | Wait for a network call to complete. Good for "login succeeded" signals. |
| `waitForTimeout` | `ms` | Dumb sleep. Avoid when possible. |

Each step takes an optional `timeout` (ms, default 30000).

**Response:**
```json
{
  "success": true,
  "finalUrl": "https://app.example.com/",
  "userAgent": "Mozilla/5.0 …",
  "cookies": [
    {"name": "sessionid", "value": "…", "domain": "app.example.com",
     "path": "/", "expires": 1234567890, "httpOnly": true, "secure": true,
     "sameSite": "None"}
  ],
  "xhrs": []
}
```

On failure, `{"success": false, "error": "TimeoutError: …"}`.

### `POST /api`

Issue an HTTP request from inside a browser context. Use this when the target
API rejects plain `requests` calls (service worker, strict Origin, JS-computed
tokens, etc.). For ordinary cookie-auth APIs, just use `requests` directly with
the cookies returned from `/login` — it's faster.

**Request:**
```json
{
  "url": "https://app.example.com/api/v1/widgets/",
  "method": "GET",
  "headers": {"Accept": "application/json"},
  "body": null,
  "cookies": [{"name":"sessionid","value":"…","domain":"app.example.com"}],
  "referer": "https://app.example.com/widgets",
  "userAgent": null,
  "viewport": {"width": 1440, "height": 900},
  "timeout": 60000
}
```

**Response:**
```json
{"success": true, "status": 200, "headers": {...}, "body": {...}, "url": "…"}
```

---

## Typical flow (from natsonhotels)

1. `scraper/login.py` → `POST /login` → writes `output/session.json` with the
   two cookies Lighthouse needs.
2. `scraper/scrape.py` → plain Python `requests` with those cookies. No browser
   touched. Runs straight on your host — no Docker per invocation.

This is the key design payoff: the browser only does the parts that actually
need a browser (2-step form, JS-sniff bypass). Everything else is cheap HTTP.

See `browser-api/examples/` for runnable Python clients of each endpoint.

---

## Caveats

- **One global fingerprint.** Camoufox is launched *once* at startup with
  `DEFAULT_UA`/`DEFAULT_OS`. Per-request `userAgent` is set at the Playwright
  context level, but the underlying Firefox build's camoufox config is fixed.
  If you need a wildly different fingerprint (e.g. a Windows build), restart
  the service with different env vars.
- **No form of stored session** across requests. Every request gets a fresh
  browser context. That's intentional (isolation). Use `/login` to get cookies
  once; pass them back into `/scrape` or `/api` on later calls.
- **Concurrency = `MAX_CONCURRENCY`.** A `/login` flow can hold a slot for
  30-45 s. Size accordingly.
- **No captcha / WebAuthn / 2FA.** The step DSL is for non-interactive login
  only. If the target site prompts for a code, you'll need to extend the
  server with a different flow.
- **Not hardened for public exposure.** There's no auth; run on `127.0.0.1`
  (the default) or behind a VPN. The Dockerfile binds to `0.0.0.0:8765` inside
  the container but compose only publishes to `localhost`.
- **Firefox version drift.** The UA default should match a recent Firefox
  release. Update `DEFAULT_UA` when Firefox ships a new major version, or
  browser-sniffing sites (Lighthouse, some banks, etc.) will reject you.
- **Login XHR capture** is handy for reverse-engineering an API. Pass
  `captureXhrUrlContains: ["/api/", "/apigateway/"]` on the first `/login`
  and you'll get the request URLs + bodies back, which makes it easy to find
  the endpoints the SPA uses.
