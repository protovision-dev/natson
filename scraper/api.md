# MyLighthouse API — reverse-engineered notes

Living document. Everything here was discovered by inspecting network traffic on
`https://app.mylighthouse.com/` while logged in as a Natson Hotels user. Not
official documentation; behavior may change without notice.

Base host: `https://app.mylighthouse.com`

---

## 1. Authentication

### Login flow
Two-step form, ultimately backed by Google Identity Platform.

| Step | Request | Notes |
|---|---|---|
| 1 | Page load `/` | SPA boots; immediately probes `/api/v3/users/?only_self=true`. Unauthenticated probe returns **401** — this is normal bootstrap, used by the SPA to detect "not logged in" and redirect to `/login`. |
| 2 | `GET /sso/login-options/?email=<urlenc>` | Returns the auth method for the email (password vs SSO). |
| 3 | `POST /apigateway/google/identityplatform/v1/accounts:signInWithPassword?key=<firebase_key>` | Google Identity Platform password exchange. Returns Firebase ID token. |
| 4 | `POST /apigateway/google/identityplatform/v1/accounts:lookup?key=<firebase_key>` | Confirms account info. |
| 5 | `GET /sso/mfa-info/?email=<urlenc>` | MFA check (none for this account). |
| 6 | `POST /sso/login/?next=%2F` | Exchanges Firebase token for a Lighthouse Django session. |

After step 6, the server sets two cookies that are sufficient for all
subsequent API calls:

| Cookie | Domain | Notes |
|---|---|---|
| `sessionid` | `app.mylighthouse.com` | HTTP-only Django session. ~24h lifetime. |
| `csrftoken` | `app.mylighthouse.com` | Required for POST/PUT, harmless on GETs. ~1y lifetime. |

Other cookies set during login (`ajs_*`, `intercom-*`, `default-hotel-v3`) are
analytics/UX state and not needed for API calls.

### Browser-version gate
The frontend redirects old user agents to `/not_supported/`. Send a current
Firefox UA to bypass:

```
Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:140.0) Gecko/20100101 Firefox/140.0
```

Also override `navigator.userAgent` in the browser context (camoufox `config={...}`)
because the JS-side check inspects that as well as the HTTP header.

### Calling the API stateless
Once you have `sessionid` + `csrftoken`, every API endpoint below works with
plain HTTP — no browser needed. Recommended request headers:

```
Cookie: sessionid=…; csrftoken=…
User-Agent: <same UA as login>
Accept: application/json, text/plain, */*
Origin: https://app.mylighthouse.com
Referer: https://app.mylighthouse.com/hotel/<hotel_id>/rates
```

---

## 2. Hotel & competitor metadata

### `GET /api/v3/hotels/?id={hotel_id}`
Returns the user's own hotel record.

```json
{
  "hotels": [{
    "id": 345062,
    "hotelinfo": 515836,
    "competitors": [2025741, 515912, 518797, 520292, 1882538, 183310, ...],
    "currency_symbol": "$",
    "currency_code": "USD",
    "otas_rates": ["branddotcom","bookingdotcom","allchannels"],
    "otas_parity": ["branddotcom","bookingdotcom","expedia","priceline","tripadvisor","googlehotelfinder"]
  }]
}
```

Key mapping: `hotel_id` (the URL/subscription ID, e.g. `345062`) ↔ `hotelinfo`
(the OTA-side ID, e.g. `515836`). All rate-grid keys are `hotelinfo` IDs.

### `GET /api/v3/hotelinfos/{hotelinfo_id}/`
Resolves a `hotelinfo` ID to a property name + geo + supported OTAs.

```json
{"hotelinfos":[{
  "id": 183310,
  "name": "Sonesta Simply Suites Austin The Domain Area",
  "hotel_group": "Sonesta International Hotels Corporation",
  "country": "US",
  "latitude": 30.3884808,
  "longitude": -97.7371661,
  "stars": 3,
  "otas": ["bookingdotcom","expedia","hotelsdotcom",...]
}]}
```

Bulk forms (`?ids=…` / `?id=…&id=…`) return **400 No valid id(s) provided** —
must call one ID at a time.

### `GET /api/v3/otas/`
Static-ish list of supported OTAs (booking.com, expedia, …). Returns 400 when
unauthenticated.

---

## 3. Rates (the main payload)

### `GET /apigateway/v1/app/rates/`

The grid view — daily rates for the hotel and all compset competitors over a
date range.

Required query params:

| Param | Example | Notes |
|---|---|---|
| `hotel_id` | `345062` | The user's own subscription/hotel ID. |
| `ota` | `bookingdotcom` | Or `branddotcom`, `allchannels`, etc. |
| `compset_ids` | `1` | The compset to load. |
| `from_date_range_start` | `2026-03-29` | Inclusive. |
| `from_date_range_end` | `2026-05-02` | Inclusive. |
| `los` | `7` | Length of stay (nights). |
| `persons` | `2` | Adults. |
| `roomtype` | `all` | Or specific room type ID. |
| `mealtype` | `0` | 0 = room only. |
| `membershiptype` | `0` | 0 = public. |
| `platform` | `-1` | -1 = any (desktop+mobile). |
| `meta` | `nested` | Response shape. |
| `bar` | `true` | Include best-available rates. |
| `flexible` | `true` | Include flex rates. |
| `rate_type` | `0` | 0 = normal. |

Date window quirk: the frontend always asks for the calendar-grid window
covering the displayed month (Sun before the 1st → Sat after last day, 35–42
days). For programmatic use you can pass any range you like.

Response shape:

```json
{
  "days":   [{"id":"2026-03-29","date":"2026-03-29","integer_date":20541}, ...],
  "periods": [
    {
      "from_date": "2026-03-29",
      "los": 7,
      "leadtime": -1,
      "day": "2026-03-29",
      "id": "2026-03-29,,7,",
      "rates": {
        "183310": [{ /* one rate cell */ }, ...],
        "1882538": [{...}],
        ...
      }
    },
    ...
  ],
  "meta": {}
}
```

Rate-cell fields (per `periods[*].rates[hotelinfo_id][N]`):

| Field | Type | Meaning |
|---|---|---|
| `value` | number | Net rate in `currency`. 0 means missing/sold-out. |
| `shop_value` | number | The "as-shopped" raw rate (often = value × los, depending on inclusion flags). |
| `currency` / `shop_currency` | string | ISO code (`USD`). |
| `hotelinfo` | int | OTA-side hotel ID. Matches `/api/v3/hotelinfos/{id}/`. |
| `ota` | string | `bookingdotcom`, etc. |
| `room_name` | string | Free text from OTA listing. Empty when missing. |
| `room_type` | string | Lighthouse-normalized type (`apartment`, `standard`, `suite`...). |
| `cema_category` | string | Category label. |
| `extract_datetime` | ISO ts | When Lighthouse last scraped this rate. |
| `best_flex` / `cancellable` / `cancellation` | bool | Cancellation policy. |
| `vat` / `city_tax` / `other_taxes` | number | Tax components. |
| `*_incl` flags | bool | Whether each tax is included in `value` vs `shop_value`. |
| `is_baserate` / `difference_with_baserate` / `position_to_baserate` | flag/num | Comparison vs base rate. |
| `is_out_of_sync` / `is_wholesale_rate` | bool | Data-quality flags. |
| `max_persons` | int | Capacity. |
| `mealtype_included` / `membershiptype` / `platform` | int | Filters echoed back. |
| `period` | string | Internal period key (`"YYYY-MM-DD,,los,"`). |
| `source_id` / `rate_code` / `rate_name` / `pos` | string | Mostly empty in practice. |
| `id` | string | Lighthouse internal rate UUID. |
| `message` | string | Error label when missing (e.g. `"general.missing"`, `"rates.soldout"`). |
| `issue_type` | int | Parity-issue tag. |
| `labels` | array | Per-rate labels. |

> **Notable:** there is **no Booking.com URL field**. To get a hotel page link
> use `/redirect` (§5).

### `GET /apigateway/v1/app/rates/historical/`
Same shape as `/rates/` but used by the rates **detail** page. Includes
historical extracts (multiple `extract_date` entries per `from_date`). Extra
params: `change_days=`, `nr_days=31`, `nr_of_days=31`, `offset=0`, `from_date`
(single date instead of range).

### `GET /apigateway/v1/app/roomtypes/rates/`
Per-roomtype mapping for compset competitors. Useful for understanding which
OTA room types Lighthouse buckets together.

```json
{"roomtypes":[{
  "id":"345062,515836,bookingdotcom,rates",
  "competitor": 515836, "hotel": 345062, "ota": "bookingdotcom",
  "roomtype_mapping":[
    {"name":"king studio - non-smoking","roomtype_id":"apartment","avg_price":63,"avg_currency":"USD"},
    ...
  ],
  "roomtype_selections":[{"id":"apartment","name":"apartment","verbose_name":"Apartment"}]
}]}
```

---

## 4. Rate Refresh ("Live Shop")

Lighthouse doesn't scrape OTAs continuously. Rates are snapshots from the last
time data was "shopped." The Refresh button in the UI triggers Lighthouse's
backend to go out and re-scrape all OTA sources for a hotel. This takes 1–3
minutes.

### `POST /apigateway/v1/app/liveshop?subscription_id={hotel_id}`

Triggers a rate refresh for one hotel and one month.

**Query params:**

| Param | Example | Notes |
|---|---|---|
| `subscription_id` | `273870` | The hotel's subscription ID (same as `hotel_id` used elsewhere). |

**Request body:**

```json
{
  "liveupdate": {
    "bulk_liveupdate_id": null,
    "completion_timestamp": null,
    "custom_range": false,
    "from_date": "2026-05-01",
    "to_date": "2026-05-31",
    "labels": "",
    "params": {
      "compset_ids": [1],
      "los": 7,
      "mealtype": 0,
      "membershiptype": 0,
      "persons": 2,
      "platform": -1,
      "roomtype": "all",
      "bar": true,
      "flexible": true,
      "rate_type": 0
    },
    "priority": 0,
    "send_email": false,
    "start_timestamp": null,
    "status": null,
    "type": "rates",
    "hotel": "273870",
    "ota": "bookingdotcom"
  }
}
```

Key body fields:

| Field | Notes |
|---|---|
| `hotel` | Subscription hotel ID as string. |
| `from_date` / `to_date` | Month boundaries. Controls which date range gets refreshed. |
| `ota` | Which OTA to re-scrape (`bookingdotcom`, `branddotcom`, etc.). |
| `params.compset_ids` | Array of compset IDs to refresh (typically `[1]`). |
| `params.los` / `persons` / `mealtype` / etc. | Must match the rate-grid params you'll query later. |
| `type` | Always `"rates"` for rate refreshes. |
| `priority` | `0` = normal. |
| `send_email` | `false` — don't email the user when done. |

**Response (200):**

```json
{
  "liveupdates": [{
    "id": 182630983,
    "hotel": 273870,
    "hotelinfo": 2760258,
    "from_date": "2026-05-01",
    "to_date": "2026-05-31",
    "nr_of_days": 31,
    "ota": "bookingdotcom",
    "status": 100,
    "completion_timestamp": "",
    "start_timestamp": "2026-04-17T00:39:46.163699+00:00",
    "los": 7,
    "persons": 2,
    "membership_type": 0,
    "priority": 0,
    "send_email": false,
    "type": "rates",
    "labels": [],
    "params": {…}
  }]
}
```

- `status: 100` = job is running.
- `completion_timestamp: ""` (or `null`) = not yet done.
- The `id` field uniquely identifies this refresh job.

**Important:**
- Max date interval per request is **one month** (31 days). Wider ranges
  return 400 with `error.liveupdate.date_interval_limit`.
- Don't trigger more than one refresh per hotel per few minutes.
  Lighthouse rate-limits refresh requests per subscription. The UI shows a
  cooldown timer after clicking Refresh.
- To refresh 3 months, POST three times (once per month), waiting for each
  to complete before the next.

### `GET /api/v3/liveupdates/?hotel_id={hotel_id}`

Polls the status of active refresh jobs.

| Param | Example | Notes |
|---|---|---|
| `hotel_id` | `273870` | Subscription hotel ID. |

**Response while refreshing:**

```json
{
  "liveupdates": [{
    "id": 182630983,
    "hotel": 273870,
    "type": "rates",
    "los": 7,
    "from_date": "2026-05-01",
    "to_date": "2026-05-31",
    "start_timestamp": "2026-04-17T00:39:46Z",
    "completion_timestamp": null,
    "status": 100,
    "nr_of_days": 31,
    "persons": 2,
    "compset_ids": "1",
    "source": "app",
    "ota": "bookingdotcom",
    "requested_by": 357220,
    "params": {…}
  }],
  "meta": {
    "limit_subscription_mid_prio_days": false,
    "limit_concurrent_user_mid_prio_shops": false,
    "limit_concurrent_subscription_high_prio_dayshop": false,
    "limit_concurrent_subscription_high_prio_monthshop": false,
    "limit_concurrent_subscription_high_prio_monthshop_brand": false,
    "limit_concurrent_user_high_prio_monthshop": false,
    "limit_concurrent_user_high_prio_monthshop_brand": false,
    "limit_daily_subscription_high_prio_monthshop": false
  }
}
```

**Response when done:**

```json
{"liveupdates": [], "meta": {…}}
```

The `liveupdates` array empties when all jobs finish. Alternatively,
`completion_timestamp` transitions from `null` to a real ISO timestamp.

**Polling recipe:**
1. `POST /liveshop` to trigger.
2. Poll `GET /liveupdates/?hotel_id=X` every 15 seconds.
3. When `liveupdates` is empty → refresh is done.
4. Now `GET /rates/` to fetch the fresh data.

The `meta` block contains rate-limit flags. If any become `true`, the
subscription has hit a refresh-frequency cap — back off or wait.

### Refresh scope and daily workflow

Each `/liveshop` POST refreshes one month for one hotel. To refresh 3 months,
POST three times (once per month), waiting for each to complete before the
next. The `from_date`/`to_date` fields control the range — set them to the
first and last day of each target month.

Typical daily workflow:
```
for each hotel:
    for each month in rolling_months():
        POST /liveshop (trigger)
        poll GET /liveupdates every 15s until empty
    for each month:
        GET /rates/ (scrape the fresh data)
```

---

## 5. Surrounding endpoints (used by the rates page)

| Endpoint | Purpose |
|---|---|
| `GET /api/v3/user_engagements_elements/` | UX onboarding state. |
| `GET /apigateway/v1/app/payment/info?hotel_id=…` | Account/billing badge. |
| `GET /apigateway/v1/app/events/accepted/?from_date_range_start=…&from_date_range_end=…&hotel_id=…&subscription_id=…` | Local events overlay. |
| `GET /apigateway/v1/app/holidays/?from_date_range_start=…&from_date_range_end=…&hotel_id=…&subscription_id=…` | Holiday overlay. |
| `GET /apigateway/v1/app/demand/ari/demands/?from_date_range_start=…&from_date_range_end=…&subscription_id=…` | Lighthouse market-demand index. |

LaunchDarkly + Segment + Intercom calls are out-of-band (analytics) and can be
ignored.

---

## 6. The `/redirect` endpoint (Booking.com deep-link)

Lighthouse does **not** include OTA URLs in the rates payload. The
"View on Booking.com" links on the rates-detail page point at a Lighthouse
redirect that 302s to the real OTA page.

### `GET /redirect`
- 301 → `/redirect/` (note trailing slash) → 302 → final OTA URL.
- Set `allow_redirects=True` on the client; final URL is on `response.url`.
- Works for any OTA in `otas_rates`/`otas_parity`, not just Booking.com.

Required query params:

| Param | Example | Notes |
|---|---|---|
| `ota` | `bookingdotcom` | Lighthouse OTA ID. |
| `hotelId` | `515836` | The competitor's `hotelinfo` ID (NOT your own `hotel_id`). |
| `direct` | `false` | Always `false` from the rates page. |
| `fromDate` | `2026-04-15` | Check-in date. |
| `los` | `7` | Length of stay → checkout = fromDate + los. |
| `persons` | `2` | `group_adults` on Booking.com. |
| `city` | `false` | Whether city tax is included in displayed rate. |
| `subscription_id` | `345062` | Your own hotel ID (for analytics attribution). |
| `pos` | `` | Point-of-sale; empty in practice. |
| `source` | `app_rates` | Lighthouse source page identifier. |

Example:
```
GET https://app.mylighthouse.com/redirect
    ?ota=bookingdotcom
    &hotelId=515836
    &direct=false
    &fromDate=2026-04-15
    &los=7
    &persons=2
    &city=false
    &subscription_id=345062
    &pos=
    &source=app_rates

Final → https://www.booking.com/hotel/us/hotel-us-hwy-northwest.html
        ?sdcid=1f&checkin=2026-04-15&checkout=2026-04-22
        &group_adults=2&selected_currency=hotel_currency
```

The Booking.com slug (`hotel-us-hwy-northwest`) is determined by `hotelId`
alone. Once resolved you can swap `checkin`/`checkout` query params for any
other date without re-hitting `/redirect`.

`chal_t=…&force_referer=` may appear when navigating from a real browser session
— that's Booking.com's anti-bot middleware appending those params after the
redirect, not Lighthouse.

---

## 7. Endpoints we tried that **don't** exist (avoid wasted calls)

All return 404 / "no valid ids":

- `/api/v3/hotelinfos/?ids=…` (bulk form rejected)
- `/api/v3/compsets/?…`, `/api/v3/compsets/{id}/`
- `/api/v3/parity-manager/issues/?…`
- `/api/v3/shops/`, `/api/v3/sources/`, `/api/v3/shop_urls/`
- `/api/v3/hotelinfos/{id}/shops/` (and `/sources/`, `/external_links/`)
- `/apigateway/v1/app/competitors/`
- `/apigateway/v1/app/shops/`, `/shop_urls/`, `/deeplinks/`, `/external_urls/`
- `/apigateway/v1/app/rates/detail/`, `/rates/details/`
- `/apigateway/v1/parity-manager/issues/`

---

## 8. Practical recipes

### Authenticate once, scrape many

Start the browser API once (idle-cheap; leave it running):

```
cd ../browser-api && docker compose up -d
```

Then from `scraper/`:

```
1. login.py   → output/session.json    (POSTs to browser-api /login; writes cookies)
2. scrape.py  → output/rates_*.json    (plain Python requests with cookies — no browser)
              + output/all_data.json   (consolidated: rates + names + Booking.com URLs)
```

Everything in step 2 runs directly on the host via the scraper venv
(`scraper/.venv/bin/python scrape.py`). No Docker invocations per call.
The browser is only touched during step 1, which happens ~daily (sessionid TTL
is ~24h).

`scrape.py` does the full pipeline in one pass:
1. Fetch `/apigateway/v1/app/rates/` for each (hotel, month) target.
2. Pull `/api/v3/hotels/?id=…` for each subscription to get its own `hotelinfo`.
3. Pull `/api/v3/hotelinfos/{id}/` for every distinct competitor `hotelinfo`.
4. Hit `/redirect` once per `(hotel, hotelinfo)` to get the Booking.com base URL.
5. Per (date, hotelinfo) cell: pick the primary rate record, swap `checkin`/`checkout`
   query params on the base URL → final per-date Booking.com link.

Steps 2–4 are slow-changing and **cached on disk** at `output/cache/`:

| Cache file | What | When to refresh |
|---|---|---|
| `cache/hotels.json` | `/api/v3/hotels/?id=X` — your own hotelinfo + compset list per subscription | When you edit a compset |
| `cache/hotelinfos.json` | `/api/v3/hotelinfos/{id}/` — property name, geo, stars, hotel group | Basically never; property metadata is static |
| `cache/booking_base_urls.json` | `/redirect` → final Booking.com URL template per `(hotel, hotelinfo)` pair | When Booking.com renames a hotel slug (rare) |

A cold run (no cache) takes ~2 min. A warm run takes ~15 s — only the 20
`/rates/` calls re-hit the wire, everything else is a dict lookup.

**To force refresh:**
```
REFRESH_META=all        .venv/bin/python scrape.py   # all three caches
REFRESH_META=hotels     .venv/bin/python scrape.py   # just subscription meta
REFRESH_META=hotelinfos .venv/bin/python scrape.py   # just property meta
REFRESH_META=urls       .venv/bin/python scrape.py   # just Booking.com URLs
```
You can also comma-combine (`REFRESH_META=hotels,urls`) or just `rm output/cache/<file>.json`.

See `../browser-api/README.md` for the browser service's endpoints, step-DSL,
and configuration options.

### Rate-grid date window for a given month
Use the same calendar grid the UI uses to ensure you get every cell that's
displayed:

```python
from datetime import date, timedelta
def grid_range(year, month):
    first = date(year, month, 1)
    days_before = (first.weekday() + 1) % 7  # Sunday = 0
    start = first - timedelta(days=days_before)
    next_month = date(year+1, 1, 1) if month == 12 else date(year, month+1, 1)
    last = next_month - timedelta(days=1)
    days_after = 6 - (last.weekday() + 1) % 7
    end = last + timedelta(days=days_after)
    return start.isoformat(), end.isoformat()
```

### Enriching rates with property names
For every distinct `hotelinfo` ID found in `periods[*].rates`, call
`/api/v3/hotelinfos/{id}/` once and cache the result. Names + lat/long persist
across months.

### Throttling & rate limits
No documented limits; observed behavior:
- 75 sequential `/redirect` calls @ 0.4s sleep ran clean.
- 20 concurrent `/rates/` calls (different hotels) ran clean from one session.
- Don't reuse one `sessionid` across many concurrent IPs — Lighthouse
  appears to bind sessions to the originating IP for some endpoints.

### Session lifetime
`sessionid` lasts ~24h. Re-run `login.py` daily.
