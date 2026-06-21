"""1lou (BT之家 1LOU, www.1lou.me) scraper.

The site has no native RSS and gates .torrent attachments behind login, so:
  1. Fetch a list page (e.g. forum-1.htm) and extract thread links + titles.
  2. For each NEW thread that passes the title filters, fetch the thread page.
  3. Find the .torrent attachment link  attach-download-<aid>.htm  and download it
     (using the operator's login Cookie).
  4. Convert the torrent to a magnet locally (see torrent.py).

The returned magnet is what gets pushed to the configured target (CloudDrive2 today).

Attachments are public, so no login is needed. A per-feed `cookie` is optional and
only used if supplied (restricted board / higher limits); ONELOU_COOKIE is the fallback.
"""
from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import urlparse

from .config import settings
from .fetcher import FetchError, fetch_bytes, fetch_text
from .torrent import TorrentError, torrent_to_magnet

log = logging.getLogger(__name__)

# <a href="thread-123456.htm" ...>Title text</a>  (title may contain nested tags)
_THREAD_LINK_RE = re.compile(
    r'href="[^"]*?thread-(\d+)\.htm"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
# <a href="attach-download-2983644.htm">Name.torrent</a>
_ATTACH_RE = re.compile(
    r'attach-download-(\d+)\.htm"[^>]*>\s*([^<]*?\.torrent)', re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")


def is_onelou(feed: dict) -> bool:
    if feed.get("kind") == "1lou":
        return True
    if feed.get("kind") == "auto":
        host = (urlparse(feed.get("url", "")).hostname or "").lower()
        return host.startswith("1lou.") or ".1lou." in host or host.endswith(".1lou.me")
    return False


def _base(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _clean_title(raw: str) -> str:
    return unescape(_TAG_RE.sub("", raw)).strip()


def _list_threads(html: str) -> list[tuple[str, str]]:
    """Return ordered, de-duplicated [(thread_id, title)] from a list page."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for m in _THREAD_LINK_RE.finditer(html):
        tid = m.group(1)
        title = _clean_title(m.group(2))
        if tid in seen or not title:
            continue
        seen.add(tid)
        out.append((tid, title))
    return out


def _resolve_thread(base: str, tid: str, cookie: str) -> str:
    """Fetch a thread, download its .torrent attachment(s), return magnet(s)."""
    thread_url = f"{base}/thread-{tid}.htm"
    html = fetch_text(thread_url, cookie=cookie)
    attachments = _ATTACH_RE.findall(html)
    if not attachments:
        raise FetchError("no .torrent attachment found on thread")

    magnets: list[str] = []
    for aid, _fname in attachments:
        data = fetch_bytes(f"{base}/attach-download-{aid}.htm", cookie=cookie)
        magnet, _name = torrent_to_magnet(data)  # raises TorrentError on login page
        if magnet not in magnets:
            magnets.append(magnet)
    return "\n".join(magnets)


def fetch_new_items(feed: dict, *, dry_run: bool, cap: int) -> tuple[list[dict], int]:
    """Return (new_items, matched_count).

    `new_items` are threads not yet seen and passing the include/exclude title
    filters. In dry-run we do NOT download torrents (no `download` set); otherwise
    each item's `download` holds newline-joined magnet link(s). Items that fail to
    resolve are returned with an `error` so the caller can record them as failed
    (which also stops them being retried every run).
    """
    from . import crud  # local import avoids a cycle

    base = _base(feed["url"])
    # Attachments are public — a cookie is optional and only used if the operator
    # supplied one (e.g. for a restricted board or to raise download limits).
    cookie = feed.get("cookie") or settings.onelou_cookie

    html = fetch_text(feed["url"], cookie=cookie)
    threads = _list_threads(html)

    inc = re.compile(feed["include_regex"], re.IGNORECASE) if feed["include_regex"] else None
    exc = re.compile(feed["exclude_regex"], re.IGNORECASE) if feed["exclude_regex"] else None

    items: list[dict] = []
    matched = 0
    for tid, title in threads:
        if inc and not inc.search(title):
            continue
        if exc and exc.search(title):
            continue
        matched += 1
        guid = f"1lou-thread-{tid}"
        if crud.item_exists(feed["id"], guid):
            continue
        if len(items) >= cap:
            break
        base_item = {
            "guid": guid,
            "title": title,
            "link": f"{base}/thread-{tid}.htm",
            "infohash": "",
            "magnet": "",
            "download": "",
        }
        if dry_run:
            items.append(base_item)
            continue
        try:
            magnet = _resolve_thread(base, tid, cookie)
            base_item["magnet"] = magnet
            base_item["download"] = magnet
        except (FetchError, TorrentError) as exc_:
            base_item["error"] = str(exc_)
            log.warning("1lou thread %s resolve failed: %s", tid, exc_)
        items.append(base_item)
    return items, matched
