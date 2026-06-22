"""Metadata scraping: Bangumi (no key, default) and TMDB (optional api key).

Returns normalized candidates: {source, id, title, name, name_cn, year, poster,
total_episodes}. The title is the best display name (zh preferred).
"""
from __future__ import annotations

import logging

import httpx

from . import appsettings

log = logging.getLogger(__name__)

UA = "bt2cd2/1.0 (+https://github.com/zzzwannasleep/bttocd2)"
BANGUMI = "https://api.bgm.tv"
TMDB = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"


def _year(date: str | None) -> str:
    return (date or "")[:4]


# ---- pure parsers (unit-tested) ------------------------------------------- #
def parse_bangumi_item(s: dict) -> dict:
    images = s.get("images") or {}
    return {
        "source": "bangumi",
        "id": str(s.get("id") or ""),
        "name": s.get("name") or "",
        "name_cn": s.get("name_cn") or "",
        "title": s.get("name_cn") or s.get("name") or "",
        "year": _year(s.get("date")),
        "poster": images.get("large") or images.get("common") or images.get("medium") or "",
        "total_episodes": s.get("total_episodes") or s.get("eps") or 0,
    }


def parse_tmdb_item(s: dict) -> dict:
    poster = s.get("poster_path")
    return {
        "source": "tmdb",
        "id": str(s.get("id") or ""),
        "name": s.get("original_name") or "",
        "name_cn": s.get("name") or "",
        "title": s.get("name") or s.get("original_name") or "",
        "year": _year(s.get("first_air_date")),
        "poster": (TMDB_IMG + poster) if poster else "",
        "total_episodes": s.get("number_of_episodes") or 0,
    }


# ---- network ------------------------------------------------------------- #
def _proxy() -> str | None:
    return appsettings.all_settings().get("http_proxy") or None


def search_bangumi(keyword: str, limit: int = 8) -> list[dict]:
    with httpx.Client(timeout=20, proxy=_proxy(), headers={"User-Agent": UA}) as c:
        r = c.post(f"{BANGUMI}/v0/search/subjects", params={"limit": limit},
                   json={"keyword": keyword, "filter": {"type": [2]}})
        r.raise_for_status()
        return [parse_bangumi_item(s) for s in r.json().get("data", [])]


def search_tmdb(keyword: str, api_key: str, limit: int = 8) -> list[dict]:
    with httpx.Client(timeout=20, proxy=_proxy()) as c:
        r = c.get(f"{TMDB}/search/tv",
                  params={"api_key": api_key, "query": keyword, "language": "zh-CN"})
        r.raise_for_status()
        return [parse_tmdb_item(s) for s in r.json().get("results", [])[:limit]]


def search(keyword: str) -> list[dict]:
    s = appsettings.all_settings()
    source = s.get("meta_source") or "bangumi"
    key = s.get("tmdb_api_key") or ""
    if source == "tmdb" and key:
        try:
            return search_tmdb(keyword, key)
        except Exception as exc:  # noqa: BLE001
            log.warning("TMDB search failed (%s); falling back to Bangumi", exc)
    return search_bangumi(keyword)
