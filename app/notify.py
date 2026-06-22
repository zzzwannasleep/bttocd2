"""Notifications: Telegram / Bark / ServerChan / generic webhook (best-effort)."""
from __future__ import annotations

import logging

import httpx

from . import appsettings

log = logging.getLogger(__name__)


def _send_telegram(token: str, chat_id: str, title: str, body: str) -> None:
    httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"*{title}*\n{body}", "parse_mode": "Markdown"},
        timeout=15,
    )


def _send_bark(url: str, title: str, body: str) -> None:
    base = url.rstrip("/")
    httpx.post(base, json={"title": title, "body": body}, timeout=15)


def _send_serverchan(key: str, title: str, body: str) -> None:
    httpx.post(f"https://sctapi.ftqq.com/{key}.send",
               data={"title": title, "desp": body}, timeout=15)


def _send_webhook(url: str, title: str, body: str) -> None:
    httpx.post(url, json={"title": title, "body": body}, timeout=15)


def send(title: str, body: str) -> list[str]:
    """Fire all configured channels. Returns the list of channels attempted."""
    s = appsettings.all_settings()
    if not s.get("notify_enabled"):
        return []
    sent: list[str] = []
    channels = [
        ("telegram", lambda: _send_telegram(s["telegram_bot_token"], s["telegram_chat_id"], title, body),
         s.get("telegram_bot_token") and s.get("telegram_chat_id")),
        ("bark", lambda: _send_bark(s["bark_url"], title, body), s.get("bark_url")),
        ("serverchan", lambda: _send_serverchan(s["serverchan_key"], title, body), s.get("serverchan_key")),
        ("webhook", lambda: _send_webhook(s["webhook_url"], title, body), s.get("webhook_url")),
    ]
    for name, fn, enabled in channels:
        if not enabled:
            continue
        try:
            fn()
            sent.append(name)
        except Exception as exc:  # noqa: BLE001
            log.warning("notify via %s failed: %s", name, exc)
    return sent


def notify_feed_result(feed_name: str, summary: dict) -> None:
    """Send a per-feed-run notification respecting the success/failure toggles."""
    s = appsettings.all_settings()
    if not s.get("notify_enabled"):
        return
    pushed, failed = summary.get("pushed", 0), summary.get("failed", 0)
    on_success = s.get("notify_on_success") and pushed > 0
    on_failure = s.get("notify_on_failure") and failed > 0
    if not (on_success or on_failure):
        return
    title = f"bt2cd2 · {feed_name}"
    body = f"新增分发 {pushed} 条，失败 {failed} 条"
    if summary.get("error"):
        body += f"\n错误: {summary['error']}"
    send(title, body)
