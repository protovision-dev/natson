"""Camoufox browser API.

A long-running FastAPI service that launches one Camoufox (stealth Firefox)
browser at startup and reuses it for every request. Each request gets its
own browser context so cookies/sessions don't leak between callers.

Endpoints:
  GET  /health           — readiness probe
  POST /scrape           — navigate to URL, return rendered HTML (+ optional XHRs)
  POST /login            — run a scripted login flow, return cookies
  POST /api              — perform an authenticated HTTP call from inside the
                           browser context (useful when a site's API requires
                           browser-only headers / JS-computed tokens)

Design notes:
  - Camoufox is launched once with a modern UA and strong fingerprint spoofing
    so sites like MyLighthouse (which browser-sniffs via JS) accept us.
  - A semaphore caps concurrent requests (default 4).
  - /login takes a list of declarative Step objects (fill / click / waitFor…).
    Anything unusual — hovers, drag-and-drop, captcha — is out of scope; build
    those directly in Playwright if you need them.
  - Cookies are returned in Playwright format: {name, value, domain, path,
    expires, httpOnly, secure, sameSite}. Consumers typically only need
    {name, value, domain, path}.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from camoufox import AsyncCamoufox
from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("browser-api")

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "4"))
DEFAULT_UA = os.environ.get(
    "DEFAULT_UA",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:140.0) Gecko/20100101 Firefox/140.0",
)
DEFAULT_OS = os.environ.get("DEFAULT_OS", "macos")
DEFAULT_LOCALE = os.environ.get("DEFAULT_LOCALE", "en-US")

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("launching camoufox (UA=%s, os=%s)...", DEFAULT_UA, DEFAULT_OS)
    launch_proxy = None
    if os.environ.get("PROXY_SERVER"):
        launch_proxy = {"server": os.environ["PROXY_SERVER"]}
        if os.environ.get("PROXY_USERNAME"):
            launch_proxy["username"] = os.environ["PROXY_USERNAME"]
        if os.environ.get("PROXY_PASSWORD"):
            launch_proxy["password"] = os.environ["PROXY_PASSWORD"]
        log.info(
            "launch-level proxy: %s (user=%s)", launch_proxy["server"], launch_proxy.get("username")
        )
    cm_kwargs = dict(
        headless="virtual",
        humanize=False,
        os=DEFAULT_OS,
        locale=DEFAULT_LOCALE,
        geoip=True,
        i_know_what_im_doing=True,
        config={
            "navigator.userAgent": DEFAULT_UA,
            "navigator.appVersion": "5.0 (Macintosh)",
            "navigator.oscpu": "Intel Mac OS X 10.15",
        },
    )
    if launch_proxy:
        cm_kwargs["proxy"] = launch_proxy
    cm = AsyncCamoufox(**cm_kwargs)
    browser = await cm.__aenter__()
    state["cm"] = cm
    state["browser"] = browser
    state["sem"] = asyncio.Semaphore(MAX_CONCURRENCY)
    state["default_ua"] = DEFAULT_UA
    log.info("camoufox ready (max_concurrency=%d)", MAX_CONCURRENCY)
    try:
        yield
    finally:
        log.info("shutting down camoufox...")
        await cm.__aexit__(None, None, None)


app = FastAPI(lifespan=lifespan, title="browser-api", version="0.1.0")


# ---------- shared models ----------


class Viewport(BaseModel):
    width: int = 1440
    height: int = 900


class Cookie(BaseModel):
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = True
    sameSite: Literal["None", "Lax", "Strict"] = "None"


class Proxy(BaseModel):
    """Playwright per-context proxy config. Tunnels all traffic from that
    single browser context (so each /scrape call can route through its own IP)."""

    server: str  # e.g. "http://gate.smartproxy.com:7000"
    username: str | None = None
    password: str | None = None
    bypass: str | None = None  # comma-sep host list that shouldn't be proxied


# ---------- /health ----------


@app.get("/health")
async def health():
    return {
        "ok": True,
        "browser": bool(state.get("browser")),
        "default_user_agent": state.get("default_ua"),
    }


# ---------- /scrape ----------


class ScrapeRequest(BaseModel):
    url: str
    waitFor: int = 0
    timeout: int = 60000
    userAgent: str | None = None
    viewport: Viewport = Field(default_factory=Viewport)
    cookies: list[Cookie] | None = None
    scrollToBottom: bool = False
    stabilitySelector: str | None = None
    scrollMaxIterations: int = 40
    scrollStepDelayMs: int = 600
    captureXhrUrlContains: list[str] | None = None
    proxy: Proxy | None = None
    # Accept self-signed / MITM certs — required when routing through a proxy
    # that inspects TLS or presents its own intermediate chain.
    ignoreHttpsErrors: bool = False


SCROLL_JS = """
() => {
    const scrollables = [document.scrollingElement, ...document.querySelectorAll('*')]
        .filter(el => {
            if (!el) return false;
            const s = getComputedStyle(el);
            const oy = s.overflowY;
            return (oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 4;
        });
    scrollables.forEach(el => { el.scrollTop = el.scrollHeight; });
    window.scrollTo(0, document.body.scrollHeight);
    return scrollables.length;
}
"""


async def _scroll_until_stable(page, req: ScrapeRequest):
    last_count = -1
    stable_iters = 0
    for _ in range(req.scrollMaxIterations):
        await page.evaluate(SCROLL_JS)
        await page.wait_for_timeout(req.scrollStepDelayMs)
        if req.stabilitySelector:
            count = await page.evaluate(
                "(sel) => document.querySelectorAll(sel).length",
                req.stabilitySelector,
            )
        else:
            count = await page.evaluate(
                "() => (document.scrollingElement || document.body).scrollHeight"
            )
        if count == last_count:
            stable_iters += 1
            if stable_iters >= 2:
                return
        else:
            stable_iters = 0
            last_count = count


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    browser = state["browser"]
    sem: asyncio.Semaphore = state["sem"]

    async with sem:
        ctx_kwargs = {
            "viewport": req.viewport.model_dump(),
            "user_agent": req.userAgent or state["default_ua"],
        }
        if req.proxy:
            p = {"server": req.proxy.server}
            if req.proxy.username:
                p["username"] = req.proxy.username
            if req.proxy.password:
                p["password"] = req.proxy.password
            if req.proxy.bypass:
                p["bypass"] = req.proxy.bypass
            ctx_kwargs["proxy"] = p
        if req.ignoreHttpsErrors:
            ctx_kwargs["ignore_https_errors"] = True
        context = await browser.new_context(**ctx_kwargs)
        try:
            if req.cookies:
                await context.add_cookies(
                    [{**c.model_dump(), "path": c.path or "/"} for c in req.cookies]
                )
            page = await context.new_page()
            page.set_default_timeout(req.timeout)

            xhrs: list[dict] = []
            if req.captureXhrUrlContains:

                async def on_resp(r):
                    if not any(s in r.url for s in req.captureXhrUrlContains):
                        return
                    try:
                        body = await r.text()
                    except Exception:
                        body = ""
                    xhrs.append(
                        {
                            "url": r.url,
                            "status": r.status,
                            "method": r.request.method,
                            "body": body[:50000],
                        }
                    )

                page.on("response", on_resp)

            await page.goto(req.url, wait_until="domcontentloaded")
            if req.waitFor:
                await page.wait_for_timeout(req.waitFor)
            if req.scrollToBottom:
                await _scroll_until_stable(page, req)

            html = await page.content()
            result: dict[str, Any] = {
                "success": True,
                "data": {"rawHtml": html, "finalUrl": page.url},
            }
            if req.captureXhrUrlContains:
                result["data"]["xhrs"] = xhrs
            return result
        except Exception as e:
            log.exception("scrape failed for %s", req.url)
            return {"success": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            await context.close()


# ---------- /login ----------


class Step(BaseModel):
    action: Literal[
        "goto",
        "fill",
        "press",
        "click",
        "waitForSelector",
        "waitForURL",
        "waitForResponse",
        "waitForTimeout",
    ]
    # Common fields (not all actions use all fields; unused ones are ignored)
    selector: str | None = None
    value: str | None = None
    key: str | None = None
    url: str | None = None
    urlContains: str | None = None
    status: int | None = None
    timeout: int = 30000
    ms: int | None = None


class LoginRequest(BaseModel):
    url: str
    steps: list[Step]
    userAgent: str | None = None
    viewport: Viewport = Field(default_factory=Viewport)
    # Pre-seed cookies into the context before navigating (for authenticated pages).
    cookies: list[Cookie] | None = None
    # Cookie filtering (applied to returned cookies, not the browser jar).
    cookieDomains: list[str] | None = None
    cookieNames: list[str] | None = None
    # Optionally capture XHRs matching any substring during the flow.
    captureXhrUrlContains: list[str] | None = None
    # Wait for networkidle on initial page load (slower but safer for SPAs).
    initialWaitUntil: Literal["domcontentloaded", "networkidle", "load"] = "networkidle"


def _filter_cookies(cookies: list[dict], req: LoginRequest) -> list[dict]:
    out = cookies
    if req.cookieDomains:
        out = [c for c in out if any(d in c.get("domain", "") for d in req.cookieDomains)]
    if req.cookieNames:
        allowed = set(req.cookieNames)
        out = [c for c in out if c.get("name") in allowed]
    return out


@app.post("/login")
async def login(req: LoginRequest):
    browser = state["browser"]
    sem: asyncio.Semaphore = state["sem"]

    async with sem:
        context = await browser.new_context(
            viewport=req.viewport.model_dump(),
            user_agent=req.userAgent or state["default_ua"],
        )
        try:
            if req.cookies:
                await context.add_cookies(
                    [{**c.model_dump(), "path": c.path or "/"} for c in req.cookies]
                )
            page = await context.new_page()

            xhrs: list[dict] = []
            if req.captureXhrUrlContains:

                async def on_resp(r):
                    if not any(s in r.url for s in req.captureXhrUrlContains):
                        return
                    try:
                        resp_body = await r.text()
                    except Exception:
                        resp_body = ""
                    req_body = None
                    if r.request.method in ("POST", "PUT", "PATCH"):
                        try:
                            req_body = r.request.post_data
                        except Exception:
                            pass
                    xhrs.append(
                        {
                            "url": r.url,
                            "status": r.status,
                            "method": r.request.method,
                            "request_body": req_body,
                            "body": resp_body[:20000],
                        }
                    )

                page.on("response", on_resp)

            log.info("login goto %s", req.url)
            await page.goto(req.url, wait_until=req.initialWaitUntil, timeout=60000)

            for i, step in enumerate(req.steps):
                a = step.action
                log.info("step %d: %s selector=%r", i + 1, a, step.selector)
                if a == "goto":
                    target = step.url or step.value
                    if not target:
                        raise ValueError("goto requires url or value")
                    await page.goto(target, wait_until="domcontentloaded", timeout=step.timeout)
                elif a == "fill":
                    await page.fill(step.selector, step.value or "", timeout=step.timeout)
                elif a == "press":
                    await page.press(step.selector, step.key or "Enter", timeout=step.timeout)
                elif a == "click":
                    await page.click(step.selector, timeout=step.timeout)
                elif a == "waitForSelector":
                    await page.wait_for_selector(step.selector, timeout=step.timeout)
                elif a == "waitForURL":
                    target = step.url or step.urlContains
                    if not target:
                        raise ValueError("waitForURL requires url or urlContains")
                    await page.wait_for_url(target, timeout=step.timeout)
                elif a == "waitForResponse":
                    needle = step.urlContains or ""
                    status = step.status

                    def _pred(r, n=needle, s=status):
                        if n and n not in r.url:
                            return False
                        if s is not None and r.status != s:
                            return False
                        return True

                    async with page.expect_response(_pred, timeout=step.timeout):
                        pass
                elif a == "waitForTimeout":
                    await page.wait_for_timeout(step.ms or 1000)

            cookies = await context.cookies()
            filtered = _filter_cookies(cookies, req)
            return {
                "success": True,
                "finalUrl": page.url,
                "userAgent": req.userAgent or state["default_ua"],
                "cookies": filtered,
                "xhrs": xhrs,
            }
        except Exception as e:
            log.exception("login failed")
            return {"success": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            await context.close()


# ---------- /api ----------


class ApiRequest(BaseModel):
    """Perform an authenticated HTTP call from inside a browser context.

    Useful when the target API ignores plain `requests` calls (needs JS-computed
    tokens, strict CORS/origin checks, or service workers). The browser issues
    the fetch(); we return the JSON body.
    """

    url: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    headers: dict[str, str] | None = None
    body: Any | None = None  # JSON-serialized for POST/PUT/PATCH
    cookies: list[Cookie] | None = None
    referer: str | None = None
    userAgent: str | None = None
    viewport: Viewport = Field(default_factory=Viewport)
    timeout: int = 60000


@app.post("/api")
async def api_call(req: ApiRequest):
    browser = state["browser"]
    sem: asyncio.Semaphore = state["sem"]

    async with sem:
        context = await browser.new_context(
            viewport=req.viewport.model_dump(),
            user_agent=req.userAgent or state["default_ua"],
        )
        try:
            if req.cookies:
                await context.add_cookies(
                    [{**c.model_dump(), "path": c.path or "/"} for c in req.cookies]
                )
            headers = dict(req.headers or {})
            if req.referer and "Referer" not in headers:
                headers["Referer"] = req.referer
            resp = await context.request.fetch(
                req.url,
                method=req.method,
                headers=headers,
                data=req.body,
                timeout=req.timeout,
            )
            ct = (resp.headers.get("content-type") or "").lower()
            if "application/json" in ct:
                body = await resp.json()
            else:
                body = await resp.text()
            return {
                "success": resp.ok,
                "status": resp.status,
                "headers": resp.headers,
                "body": body,
                "url": resp.url,
            }
        except Exception as e:
            log.exception("api call failed for %s %s", req.method, req.url)
            return {"success": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            await context.close()
