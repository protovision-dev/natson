"""Open the compset management page, type in the search box, and capture any XHRs."""

import asyncio
import json
from pathlib import Path

from camoufox.async_api import AsyncCamoufox

OUT = Path("/out")
SESSION = json.loads((OUT / "session.json").read_text())
UA = SESSION["user_agent"]

# URL for compset / settings page — Lighthouse typically exposes compset
# editing under /hotel/{id}/settings/compsets or similar.
CANDIDATES = [
    "https://app.mylighthouse.com/hotel/345062/settings/compsets",
    "https://app.mylighthouse.com/hotel/345062/settings/compset",
    "https://app.mylighthouse.com/hotel/345062/compset",
    "https://app.mylighthouse.com/hotel/345062/compsets",
    "https://app.mylighthouse.com/hotel/345062/settings",
    "https://app.mylighthouse.com/hotel/345062/account/compsets",
]


async def main():
    captured = []

    async with AsyncCamoufox(
        headless="virtual",
        humanize=True,
        os="macos",
        locale="en-US",
        geoip=True,
        i_know_what_im_doing=True,
        config={"navigator.userAgent": UA},
    ) as browser:
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000}, user_agent=UA)
        await ctx.add_cookies(
            [
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
        )
        page = await ctx.new_page()

        async def on_resp(r):
            u = r.url
            if "mylighthouse.com" in u and "json" in (r.headers or {}).get("content-type", ""):
                try:
                    body = await r.text()
                except Exception:
                    body = ""
                captured.append(
                    {
                        "url": u,
                        "status": r.status,
                        "method": r.request.method,
                        "body_snip": body[:800],
                    }
                )

        page.on("response", on_resp)

        for cand in CANDIDATES:
            print(f"\n[*] GET {cand}")
            try:
                await page.goto(cand, wait_until="networkidle", timeout=60000)
            except Exception as e:
                print(f"   nav err: {e}")
                continue
            print(f"   landed at: {page.url}")
            await page.wait_for_timeout(2500)

            # Look for any input that looks like a hotel search.
            boxes = await page.evaluate(
                r"""() => {
                    const out = [];
                    document.querySelectorAll('input, textarea').forEach(el => {
                        const p = (el.placeholder || '').toLowerCase();
                        const t = (el.type || '').toLowerCase();
                        if (/hotel|competitor|search|property|find/.test(p) ||
                            /search/.test(t)) {
                            out.push({tag: el.tagName, placeholder: el.placeholder,
                                      type: el.type, name: el.name,
                                      cls: (el.className||'').slice(0,80)});
                        }
                    });
                    return out.slice(0, 10);
                }"""
            )
            print(f"   candidate inputs: {len(boxes)}")
            for b in boxes[:5]:
                print(f"      {b}")

            if boxes:
                # Try typing into the first search-looking field.
                try:
                    ph = boxes[0]["placeholder"] or ""
                    if ph:
                        loc = page.locator(f"input[placeholder='{ph}']").first
                    else:
                        loc = page.locator("input[type=search]").first
                    if await loc.count():
                        await loc.click()
                        await loc.type("motel 6", delay=60)
                        await page.wait_for_timeout(3000)
                        print("   typed into search box")
                except Exception as e:
                    print(f"   type err: {e}")

    (OUT / "compset_xhrs.json").write_text(json.dumps(captured, indent=2, default=str))
    print(f"\n[*] captured {len(captured)} JSON XHRs")
    for x in captured:
        print(f"   {x['method']} {x['status']} {x['url'][:140]}")
        if (
            "motel" in x["body_snip"].lower()
            or "search" in x["url"].lower()
            or "compset" in x["url"].lower()
        ):
            print(f"      ↳ {x['body_snip'][:300]}")


if __name__ == "__main__":
    asyncio.run(main())
