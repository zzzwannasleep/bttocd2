"""Runtime-editable settings, persisted in the DB and layered over env defaults.

Crawl/anti-block keys are mirrored onto the live `config.settings` object so the
fetcher/scheduler (which read it at call time) pick changes up without a restart.
Notification keys are read by notify.py.
"""
from __future__ import annotations

import json
import logging

from . import fetcher
from .config import settings
from .database import get_conn

log = logging.getLogger(__name__)

# key -> python type used for coercion/validation
CRAWL_KEYS = {
    "host_min_interval": int,
    "fetch_jitter_seconds": int,
    "default_interval_minutes": int,
    "max_items_per_run": int,
    "flaresolverr_url": str,
    "http_proxy": str,
}
NOTIFY_KEYS = {
    "notify_enabled": bool,
    "notify_on_success": bool,
    "notify_on_failure": bool,
    "telegram_bot_token": str,
    "telegram_chat_id": str,
    "bark_url": str,
    "serverchan_key": str,
    "webhook_url": str,
}
META_KEYS = {
    "meta_source": str,       # 'bangumi' | 'tmdb'
    "tmdb_api_key": str,
    "library_root": str,      # default Emby/Jellyfin library root
}
ALL_KEYS = {**CRAWL_KEYS, **NOTIFY_KEYS, **META_KEYS}

STATE: dict = {}


def _defaults() -> dict:
    return {
        "host_min_interval": settings.host_min_interval,
        "fetch_jitter_seconds": settings.fetch_jitter_seconds,
        "default_interval_minutes": settings.default_interval_minutes,
        "max_items_per_run": settings.max_items_per_run,
        "flaresolverr_url": settings.flaresolverr_url,
        "http_proxy": settings.http_proxy,
        "notify_enabled": False,
        "notify_on_success": True,
        "notify_on_failure": True,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "bark_url": "",
        "serverchan_key": "",
        "webhook_url": "",
        "meta_source": "bangumi",
        "tmdb_api_key": "",
        "library_root": "",
    }


def _coerce(key: str, value):
    typ = ALL_KEYS.get(key, str)
    if typ is bool:
        return bool(value)
    if typ is int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    return str(value or "")


def _apply(data: dict) -> None:
    STATE.clear()
    STATE.update(data)
    settings.host_min_interval = data["host_min_interval"]
    settings.fetch_jitter_seconds = data["fetch_jitter_seconds"]
    settings.default_interval_minutes = data["default_interval_minutes"]
    settings.max_items_per_run = data["max_items_per_run"]
    settings.flaresolverr_url = data["flaresolverr_url"]
    settings.http_proxy = data["http_proxy"]
    fetcher.set_proxy(data["http_proxy"])


def load() -> None:
    data = _defaults()
    with get_conn() as conn:
        for key, value in conn.execute("SELECT key, value FROM settings"):
            if key in ALL_KEYS:
                try:
                    data[key] = _coerce(key, json.loads(value))
                except (json.JSONDecodeError, TypeError):
                    data[key] = _coerce(key, value)
    _apply(data)
    log.info("Settings loaded (notify=%s)", data["notify_enabled"])


def all_settings() -> dict:
    return dict(STATE)


def update(new: dict) -> dict:
    merged = dict(STATE)
    for key, value in new.items():
        if key in ALL_KEYS:
            merged[key] = _coerce(key, value)
    # clamp a few sane bounds
    merged["host_min_interval"] = max(1, merged["host_min_interval"])
    merged["default_interval_minutes"] = max(5, merged["default_interval_minutes"])
    merged["max_items_per_run"] = max(1, merged["max_items_per_run"])
    with get_conn() as conn:
        for key in ALL_KEYS:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(merged[key])),
            )
    _apply(merged)
    return all_settings()
