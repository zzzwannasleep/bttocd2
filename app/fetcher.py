"""HTTP fetching tuned to stay under site rate limits and survive Cloudflare.

Strategy:
- One shared cloudscraper session (solves Cloudflare's JS / IUAM challenge).
- Per-host minimum interval + random jitter so we never hammer a site.
- Rotating User-Agent.
- Optional FlareSolverr backend for hard challenges (Turnstile / managed).
- Exponential backoff memory: a host that returns 403/429 is cooled down.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from urllib.parse import urlparse

import cloudscraper
import httpx

from .config import settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_last_fetch: dict[str, float] = {}      # host -> last request monotonic time
_cooldown_until: dict[str, float] = {}  # host -> do not fetch before this time


class FetchError(Exception):
    pass


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _scraper() -> "cloudscraper.CloudScraper":
    sc = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False},
        delay=10,
    )
    if settings.http_proxy:
        sc.proxies = {"http": settings.http_proxy, "https": settings.http_proxy}
    return sc


_session = _scraper()


def set_proxy(proxy: str) -> None:
    """Update the shared session's proxy at runtime (from the settings page)."""
    _session.proxies = {"http": proxy, "https": proxy} if proxy else {}


def _respect_rate_limit(host: str) -> None:
    """Block until it's polite to hit `host` again (jitter included)."""
    with _lock:
        now = time.monotonic()
        cooldown = _cooldown_until.get(host, 0)
        last = _last_fetch.get(host, 0)
        wait = 0.0
        if cooldown > now:
            wait = cooldown - now
        else:
            elapsed = now - last
            if elapsed < settings.host_min_interval:
                wait = settings.host_min_interval - elapsed
        # Reserve the slot now so concurrent callers serialize per host.
        scheduled = now + wait + random.uniform(0, settings.fetch_jitter_seconds)
        _last_fetch[host] = scheduled
    delay = scheduled - time.monotonic()
    if delay > 0:
        log.debug("rate-limit: sleeping %.1fs before hitting %s", delay, host)
        time.sleep(delay)


def _cool_down(host: str, seconds: float) -> None:
    with _lock:
        _cooldown_until[host] = time.monotonic() + seconds
    log.warning("Cooling down %s for %.0fs", host, seconds)


def _fetch_flaresolverr(url: str) -> str:
    endpoint = settings.flaresolverr_url.rstrip("/") + "/v1"
    payload = {"cmd": "request.get", "url": url, "maxTimeout": settings.request_timeout * 1000}
    with httpx.Client(timeout=settings.request_timeout + 15) as client:
        r = client.post(endpoint, json=payload)
        r.raise_for_status()
        data = r.json()
    if data.get("status") != "ok":
        raise FetchError(f"FlareSolverr error: {data.get('message')}")
    return data["solution"]["response"]


def _do_get(url: str, cookie: str = "", accept: str = "*/*"):
    """Shared request path: rate-limit, headers, cooldown on block."""
    host = _host(url)
    if not host:
        raise FetchError(f"Invalid URL: {url}")
    _respect_rate_limit(host)

    headers = {
        "User-Agent": random.choice(settings.user_agents),
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    try:
        resp = _session.get(url, headers=headers, timeout=settings.request_timeout)
    except Exception as exc:
        _cool_down(host, settings.host_min_interval * 2)
        raise FetchError(f"request failed: {exc}") from exc

    if resp.status_code in (403, 429, 503):
        _cool_down(host, settings.host_min_interval * 4)
        raise FetchError(f"blocked (HTTP {resp.status_code}) — possible Cloudflare/rate limit")
    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code}")
    return resp


def fetch_text(url: str, cookie: str = "") -> str:
    """Fetch a URL as text, honoring rate limits and Cloudflare protection."""
    if settings.flaresolverr_url:
        try:
            _respect_rate_limit(_host(url))
            return _fetch_flaresolverr(url)
        except FetchError:
            raise
        except Exception as exc:  # fall back to cloudscraper
            log.warning("FlareSolverr failed (%s); falling back to cloudscraper", exc)
    return _do_get(url, cookie, "application/rss+xml, application/xml, text/xml, text/html, */*;q=0.8").text


def fetch_bytes(url: str, cookie: str = "") -> bytes:
    """Fetch raw bytes (e.g. a .torrent). Always via cloudscraper, never FlareSolverr."""
    return _do_get(url, cookie, "application/x-bittorrent, application/octet-stream, */*").content
