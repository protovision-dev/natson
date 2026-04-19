"""Scrape Booking.com directly via our local browser-api (no Firecrawl).

Replaces firecrawl_may.py. Loads each hotel page through browser-api /scrape,
extracts the b_rooms_available_and_soldout JSON blob embedded in the HTML,
computes the lowest 7-night price, and writes a sidecar JSON comparable to
firecrawl_may.json.

Paced conservatively with a random delay between requests to avoid tripping
Booking.com's bot detection. Stops the run early if several consecutive
requests come back looking like a challenge page.
"""

import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

OUT = Path(os.environ.get("OUT_DIR", "output"))
ALL_DATA = OUT / "all_data.json"
HTML_DIR = OUT / "booking_html"
RAW_DIR = OUT / "booking_raw"
API = os.environ.get("BROWSER_API", "http://localhost:8765")


def load_proxy() -> dict | None:
    """Parse ../smartproxy.txt (key: value lines) into a Playwright proxy dict."""
    path = Path("../smartproxy.txt")
    if not path.exists():
        return None
    kv = {}
    for line in path.read_text().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        kv[k.strip().lower()] = v.strip()
    server = kv.get("proxy server") or kv.get("proxy_server")
    port = kv.get("port")
    user = kv.get("username")
    pw = kv.get("password")
    if not (server and port and user and pw):
        return None
    return {
        "server": f"http://{server}:{port}",
        "username": user,
        "password": pw,
    }


PROXY = load_proxy()

CHECKIN = os.environ.get("CHECKIN", "2026-05-13")
CHECKOUT = os.environ.get("CHECKOUT", "2026-05-20")

# Pacing. `b_rooms_available_and_soldout` is server-rendered into the initial
# HTML, so we don't need to wait for JS — a brief waitFor is plenty. The
# per-worker delay is where "polite" happens; sustained rate stays ≈1 req/sec
# with CONCURRENCY=3 and DELAY_MIN=2.
CONCURRENCY = int(os.environ.get("CONCURRENCY", "4"))
# With rotating residential proxy, per-IP throttling doesn't apply — we can
# run tighter. Still small jitter so we don't hammer the proxy gateway.
DELAY_MIN_S = float(os.environ.get("DELAY_MIN_S", "0.5"))
DELAY_MAX_S = float(os.environ.get("DELAY_MAX_S", "1.5"))

# Stop if we've accumulated several blocked-looking responses, so one bad run
# doesn't burn through the whole list after we've already been flagged.
MAX_BLOCKS = int(os.environ.get("MAX_BLOCKS", "8"))

# Booking.com fronts pages with an AWS WAF JS challenge that takes several
# seconds to solve and then calls window.location.reload(true). Our waitFor
# has to cover (challenge solve + reload + real-page render). ~10s works
# reliably from tests.
WAIT_FOR_MS = int(os.environ.get("WAIT_FOR_MS", "10000"))
TIMEOUT_MS = int(os.environ.get("TIMEOUT_MS", "90000"))

# Specific signatures of challenge/block pages — these are unique enough not
# to appear on a normal Booking hotel page. (Generic words like "captcha" or
# "chal_t" appear in embedded URL templates on legitimate pages.)
BLOCK_MARKERS = [
    "AwsWafIntegration",  # AWS WAF JS challenge page
    'id="challenge-container"',  # challenge DOM node
    "cf-browser-verification",  # Cloudflare's JS challenge
    "Pardon our interruption",  # Booking/Akamai's block interstitial
]

OUT_FILE = OUT / "booking_direct.json"


# ---------- helpers ----------


def lock_dates(url: str, checkin: str, checkout: str) -> str:
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["checkin"] = checkin
    q["checkout"] = checkout
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def collect_urls() -> list[dict]:
    """One row per (subscription, hotelinfo) with a non-zero May rate,
    deduped by Booking.com slug. Mirrors firecrawl_may.collect_urls()."""
    data = json.loads(ALL_DATA.read_text())
    out: list[dict] = []
    seen_slugs: set[str] = set()

    for sub in data["subscriptions"]:
        may = next((m for m in sub["months"] if m["month"] == "2026-05"), None)
        if not may:
            continue
        names: dict[str, str] = {}
        bases: dict[str, str] = {}
        if sub.get("own_hotelinfo"):
            names[sub["own_hotelinfo"]["id"]] = sub["own_hotelinfo"]["name"]
            if sub["own_hotelinfo"].get("booking_base_url"):
                bases[sub["own_hotelinfo"]["id"]] = sub["own_hotelinfo"]["booking_base_url"]
        for c in sub["competitors"]:
            names[c["hotelinfo_id"]] = c["name"]
            if c.get("booking_base_url"):
                bases[c["hotelinfo_id"]] = c["booking_base_url"]

        rate_row = next((r for r in may["rates_by_date"] if r["date"] == CHECKIN), None)

        for hi_id, base_url in bases.items():
            slug = urlsplit(base_url).path
            if slug in seen_slugs:
                continue

            lh_rate = None
            if rate_row:
                lh_rate = rate_row["competitors"].get(hi_id)
            if not lh_rate or (lh_rate.get("value") or 0) == 0:
                for r in may["rates_by_date"]:
                    rec = r["competitors"].get(hi_id)
                    if rec and (rec.get("value") or 0) > 0:
                        lh_rate = rec
                        break
            if not lh_rate:
                continue

            seen_slugs.add(slug)
            out.append(
                {
                    "subscription_hotel_id": sub["hotel_id"],
                    "subscription_hotel_name": sub["hotel_name"],
                    "hotelinfo_id": hi_id,
                    "property_name": names.get(hi_id, "?"),
                    "checkin": CHECKIN,
                    "checkout": CHECKOUT,
                    "booking_url": lock_dates(base_url, CHECKIN, CHECKOUT),
                    "lighthouse_value_per_night": lh_rate.get("value"),
                    "lighthouse_shop_value": lh_rate.get("shop_value"),
                    "lighthouse_currency": lh_rate.get("currency"),
                    "lighthouse_room_name": lh_rate.get("room_name"),
                    "lighthouse_message": lh_rate.get("message"),
                }
            )
    return out


def browser_scrape(url: str) -> dict:
    """POST to our local browser-api /scrape; returns {status, html, finalUrl, error}."""
    payload = {
        "url": url,
        "waitFor": WAIT_FOR_MS,
        "timeout": TIMEOUT_MS,
        "viewport": {"width": 1440, "height": 900},
        "ignoreHttpsErrors": True,
    }
    # Proxy is configured at browser-api launch level (PROXY_* env vars in
    # compose.yaml) because Firefox/Camoufox doesn't honor per-context proxy
    # reliably. We don't need to pass it per request.
    try:
        r = requests.post(f"{API}/scrape", json=payload, timeout=TIMEOUT_MS / 1000 + 30)
    except Exception as e:
        return {"status": 0, "html": "", "finalUrl": "", "error": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {
            "status": r.status_code,
            "html": "",
            "finalUrl": "",
            "error": f"HTTP {r.status_code}: {r.text[:200]}",
        }
    body = r.json()
    if not body.get("success"):
        return {
            "status": r.status_code,
            "html": "",
            "finalUrl": "",
            "error": body.get("error") or "unknown",
        }
    data = body["data"]
    return {
        "status": 200,
        "html": data["rawHtml"],
        "finalUrl": data.get("finalUrl") or "",
        "error": None,
    }


def _walk_brackets(html: str, start: int, open_char: str, close_char: str) -> int:
    """Given html[start] == open_char, return the index just past the matching close."""
    depth = 0
    i = start
    in_string = False
    escape = False
    while i < len(html):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return -1


def _find_js_literal(html: str, key: str, open_char: str) -> str | None:
    """Find `{key}: {literal}` in the HTML and return the literal text."""
    i = html.find(key)
    if i < 0:
        return None
    i += len(key)
    while i < len(html) and html[i] in " \t\n":
        i += 1
    if i >= len(html) or html[i] != open_char:
        return None
    close_char = "]" if open_char == "[" else "}"
    end = _walk_brackets(html, i, open_char, close_char)
    if end < 0:
        return None
    return html[i:end]


def extract_room_blob(html: str) -> list | None:
    """Extract b_rooms_available_and_soldout: [...] from the HTML."""
    literal = _find_js_literal(html, "b_rooms_available_and_soldout:", "[")
    if literal is None:
        return None
    try:
        return json.loads(literal)
    except Exception:
        return None


def extract_ld_json(html: str) -> list[dict]:
    """Pull every <script type='application/ld+json'> blob."""
    out = []
    for m in re.finditer(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.S | re.I,
    ):
        try:
            out.append(json.loads(m.group(1).strip()))
        except Exception:
            pass
    return out


def extract_meta_tags(html: str) -> dict:
    """<meta name=... / property=... content=...> pairs that are cheap signal."""
    out: dict = {}
    for m in re.finditer(
        r"<meta\s+(?:name|property)=[\"\']([^\"\']+)[\"\']\s+content=[\"\']([^\"\']*)[\"\']",
        html,
        re.I,
    ):
        out[m.group(1)] = m.group(2)
    return out


def extract_hprt_rows(html: str) -> list[dict]:
    """Each hprt-table row has data-block-id + data-room-id plus a set of data-*
    attributes worth keeping. Grab them verbatim."""
    rows = []
    for m in re.finditer(r"<tr[^>]*js-rt-block-row[^>]*>", html):
        row_html = m.group(0)
        attrs = dict(re.findall(r"(data-[\w-]+)=[\"\']([^\"\']*)[\"\']", row_html))
        rows.append(attrs)
    return rows


def extract_photos(html: str) -> list[str]:
    return sorted(
        set(
            re.findall(
                r"https?://[a-z0-9.-]+bstatic\.com/xdata/images/hotel/[a-zA-Z0-9_/.-]+\.(?:jpg|webp)",
                html,
            )
        )
    )[:50]


def extract_everything(html: str) -> dict:
    """All the structured data we can get out of one Booking.com hotel page."""
    rooms = extract_room_blob(html)
    return {
        "rooms": rooms,  # full b_rooms_available_and_soldout blob — nothing trimmed
        "ld_json": extract_ld_json(html),
        "meta_tags": extract_meta_tags(html),
        "hprt_rows": extract_hprt_rows(html),
        "photos": extract_photos(html),
    }


def summarize_blob(rooms: list, min_persons: int = 2) -> dict:
    """Pick the lowest 7-night price that fits at least min_persons guests."""
    n_types = len(rooms)
    n_blocks = sum(len(rt.get("b_blocks") or []) for rt in rooms)
    best = None
    for rt in rooms:
        for b in rt.get("b_blocks") or []:
            if (b.get("b_max_persons") or 0) < min_persons:
                continue
            try:
                raw = float(b.get("b_raw_price") or 0)
            except Exception:
                continue
            if raw <= 0:
                continue
            if best is None or raw < best["raw"]:
                best = {
                    "raw": raw,
                    "display": b.get("b_price"),
                    "room_type_id": rt.get("b_roomtype_id"),
                    "block_id": b.get("b_block_id"),
                    "max_persons": b.get("b_max_persons"),
                    "cancellation_type": b.get("b_cancellation_type"),
                    "mealplan": b.get("b_mealplan_included_name"),
                    "book_now_pay_later": b.get("b_book_now_pay_later"),
                }
    return {
        "n_room_types": n_types,
        "n_room_blocks": n_blocks,
        "sold_out": best is None and n_blocks == 0,
        "lowest_raw_price": best["raw"] if best else None,
        "lowest_price_display": best["display"] if best else None,
        "room_type_id": best["room_type_id"] if best else None,
        "block_id": best["block_id"] if best else None,
        "max_persons": best["max_persons"] if best else None,
        "cancellation_type": best["cancellation_type"] if best else None,
        "mealplan": best["mealplan"] if best else None,
    }


def looks_blocked(html: str, final_url: str) -> bool:
    if not html or len(html) < 5000:
        return True
    # If the real rate table is in the HTML, it's a good page — trust that
    # over any other heuristic.
    if "b_rooms_available_and_soldout" in html:
        return False
    if any(m in html for m in BLOCK_MARKERS):
        return True
    # Only treat chal_t in the final URL as a block signal when the page
    # itself is also small (already handled above) — otherwise it's noise.
    return False


# ---------- main ----------


def save(results: list) -> None:
    OUT_FILE.write_text(
        json.dumps(
            {
                "scraped_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "checkin": CHECKIN,
                "checkout": CHECKOUT,
                "pacing_seconds": [DELAY_MIN_S, DELAY_MAX_S],
                "results": results,
            },
            indent=2,
            default=str,
        )
    )


def main() -> int:
    targets = collect_urls()
    if not targets:
        print(f"[!] no May targets in {ALL_DATA}", file=sys.stderr)
        return 2
    # Quick health check.
    try:
        h = requests.get(f"{API}/health", timeout=5).json()
    except Exception as e:
        print(f"[!] browser-api not reachable at {API}: {e}", file=sys.stderr)
        return 2
    if not h.get("browser"):
        print(f"[!] browser-api reports browser=false: {h}", file=sys.stderr)
        return 2

    print(f"[*] {len(targets)} URLs — check-in={CHECKIN} / check-out={CHECKOUT}")
    print(f"[*] abort after {MAX_BLOCKS} total blocked responses")

    HTML_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Shared state for concurrency.
    lock = threading.Lock()
    state = {"blocks": 0, "done": 0, "total": len(targets)}
    abort = threading.Event()

    def worker(t: dict) -> dict:
        if abort.is_set():
            return {**t, "browser_error": "aborted before start", "extracted_at": None}
        scraped = browser_scrape(t["booking_url"])
        html = scraped["html"]
        blocked = looks_blocked(html, scraped["finalUrl"])
        stem = f"{t['hotelinfo_id']}_{t['checkin']}"
        if html:
            (HTML_DIR / f"{stem}.html").write_text(html)
        everything = extract_everything(html) if not blocked and html else None
        summary = (
            summarize_blob(everything["rooms"]) if everything and everything["rooms"] else None
        )
        if everything:
            (RAW_DIR / f"{stem}.json").write_text(json.dumps(everything, indent=2, default=str))

        with lock:
            state["done"] += 1
            if blocked:
                state["blocks"] += 1
            n = state["done"]
            blocks = state["blocks"]
        if blocked:
            tag = f"⚠ blocked ({blocks}/{MAX_BLOCKS})"
        elif summary is None:
            tag = "? no room blob"
        elif summary["sold_out"]:
            tag = "SOLD OUT"
        else:
            tag = f"${summary['lowest_raw_price']} ({summary['n_room_blocks']} blocks)"
        print(f"[{n}/{state['total']}] {t['property_name'][:50]:<50}  {tag}", flush=True)

        if blocked and state["blocks"] >= MAX_BLOCKS:
            abort.set()

        # Polite jittered delay INSIDE the worker so concurrent workers stagger.
        time.sleep(random.uniform(DELAY_MIN_S, DELAY_MAX_S))

        return {
            **t,
            "browser_http_status": scraped["status"],
            "browser_final_url": scraped["finalUrl"],
            "browser_blocked": blocked,
            "browser_html_size": len(html),
            "browser_error": scraped["error"],
            "browser_extracted": summary,
            "html_file": f"booking_html/{stem}.html" if html else None,
            "raw_file": f"booking_raw/{stem}.json" if everything else None,
            "extracted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    results: list[dict] = []
    print(
        f"[*] concurrency={CONCURRENCY}  waitFor={WAIT_FOR_MS}ms  delay={DELAY_MIN_S}-{DELAY_MAX_S}s"
    )
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = [ex.submit(worker, t) for t in targets]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            # Checkpoint every 10 completions.
            if i % 10 == 0:
                save(results)
            if abort.is_set():
                # Let in-flight workers finish; don't submit more (they're already submitted).
                pass
    if abort.is_set():
        print(
            f"\n[!] {state['blocks']} blocked responses — aborting; partial output written.",
            flush=True,
        )
        save(results)
        return 3

    save(results)
    n_ok = sum(
        1 for r in results if r.get("browser_extracted") and not r["browser_extracted"]["sold_out"]
    )
    n_sold = sum(
        1 for r in results if r.get("browser_extracted") and r["browser_extracted"]["sold_out"]
    )
    n_blocked = sum(1 for r in results if r.get("browser_blocked"))
    n_weird = sum(
        1 for r in results if r.get("browser_extracted") is None and not r.get("browser_blocked")
    )
    print(f"\n[*] wrote {OUT_FILE}")
    print(
        f"    priced: {n_ok}   sold out: {n_sold}   blocked: {n_blocked}   no-blob: {n_weird}   total: {len(results)}"
    )
    return 0 if (n_ok + n_sold) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
