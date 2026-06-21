"""RSS/Atom parsing and magnet/torrent extraction.

Works for dmhy, 動漫花園, BtHome/1lou, nyaa, and generic torrent feeds. We try
hard to find a magnet link or a .torrent URL for each entry, plus a stable
dedup key (infohash preferred, else GUID/link).
"""
from __future__ import annotations

import re
from typing import Any

import feedparser

_MAGNET_RE = re.compile(r"magnet:\?[^\s\"'<>]+", re.IGNORECASE)
_BTIH_RE = re.compile(r"xt=urn:bt[im]h:([0-9a-z]+)", re.IGNORECASE)


def _infohash_from_magnet(magnet: str) -> str:
    m = _BTIH_RE.search(magnet or "")
    return m.group(1).lower() if m else ""


def _extract_links(entry: Any) -> tuple[str, str]:
    """Return (magnet, torrent_url) best-effort from a feed entry."""
    magnet = ""
    torrent = ""

    # 1) enclosures (dmhy / nyaa put magnet or .torrent here)
    for enc in getattr(entry, "enclosures", []) or []:
        href = (enc.get("href") or enc.get("url") or "").strip()
        if href.lower().startswith("magnet:"):
            magnet = href
        elif href.lower().endswith(".torrent") or "torrent" in (enc.get("type") or "").lower():
            torrent = href

    # 2) <link> may itself be a magnet
    link = (getattr(entry, "link", "") or "").strip()
    if not magnet and link.lower().startswith("magnet:"):
        magnet = link

    # 3) scan title/summary/content for a magnet URI
    if not magnet:
        blobs = [getattr(entry, "summary", "") or "", getattr(entry, "title", "") or ""]
        for c in getattr(entry, "content", []) or []:
            blobs.append(c.get("value", ""))
        for blob in blobs:
            found = _MAGNET_RE.search(blob)
            if found:
                magnet = found.group(0)
                break

    return magnet, torrent


def parse_feed(text: str) -> list[dict[str, str]]:
    """Parse feed text into a list of normalized item dicts."""
    parsed = feedparser.parse(text)
    items: list[dict[str, str]] = []
    for entry in parsed.entries:
        magnet, torrent = _extract_links(entry)
        download = magnet or torrent
        if not download:
            continue  # nothing actionable
        infohash = _infohash_from_magnet(magnet)
        guid = (
            getattr(entry, "id", "")
            or getattr(entry, "guid", "")
            or infohash
            or download
        )
        items.append(
            {
                "guid": str(guid),
                "infohash": infohash,
                "title": (getattr(entry, "title", "") or "").strip(),
                "link": (getattr(entry, "link", "") or "").strip(),
                "magnet": magnet,
                "torrent": torrent,
                "download": download,
            }
        )
    return items


def apply_filters(items: list[dict[str, str]], include: str, exclude: str) -> list[dict[str, str]]:
    """Keep items whose title matches `include` (if set) and not `exclude`."""
    inc = re.compile(include, re.IGNORECASE) if include else None
    exc = re.compile(exclude, re.IGNORECASE) if exclude else None
    out = []
    for it in items:
        title = it.get("title", "")
        if inc and not inc.search(title):
            continue
        if exc and exc.search(title):
            continue
        out.append(it)
    return out
