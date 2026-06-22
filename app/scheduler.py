"""Polling scheduler.

A single background "tick" runs every minute, finds feeds that are due, and
processes them sequentially. Sequential processing + per-host rate limiting in
fetcher.py is deliberate: it keeps load on the BT sites low and predictable,
which is the best defense against rate-limit bans.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from . import appsettings, crud, episode, naming, notify, onelou, targets as targets_mod
from .config import settings
from .database import now
from .fetcher import FetchError, fetch_text
from .rss import apply_filters, parse_feed

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _plan_location(feed: dict, item: dict) -> str:
    """If the feed has scraped metadata + rename enabled, organize this item into
    an Emby/Jellyfin folder and record the planned path on the item. Returns the
    download location to use for the target."""
    base_location = feed.get("target_folder") or ""
    if not (feed.get("rename_enabled") and (feed.get("title_cn") or feed.get("original_title"))):
        return base_location
    ep = episode.parse_episode(item.get("title", ""))
    if ep is None:
        return base_location  # can't place it without an episode number
    ep = episode.apply_offset(ep, feed.get("episode_offset") or 0)
    meta = {"title": feed.get("title_cn") or feed.get("original_title"), "year": feed.get("year")}
    plan = naming.build(meta, feed.get("season") or 1, ep, feed.get("rename_template") or None)
    root = (feed.get("library_path") or appsettings.all_settings().get("library_root") or "").rstrip("/")
    location = f"{root}/{plan['folder']}" if root else plan["folder"]
    item["dest"] = plan["full"] + ".*"
    return location


def _dispatch(feed: dict, urls: str, location: str) -> None:
    """Send resolved URLs to the feed's configured target."""
    tid = feed.get("target_id")
    if not tid:
        raise targets_mod.TargetError("该源未配置分发目标")
    target_row = crud.get_target(tid, mask=False)
    if not target_row:
        raise targets_mod.TargetError("分发目标不存在（已被删除？）")
    if not target_row["enabled"]:
        raise targets_mod.TargetError(f"目标「{target_row['name']}」已停用")
    target = targets_mod.make_target(target_row["type"], target_row["config"])
    target.add(urls, location)


def _collect_rss(feed: dict, dry_run: bool) -> tuple[list[dict], int]:
    """RSS sources (dmhy / nyaa / generic): parse, filter, dedup."""
    text = fetch_text(feed["url"])
    items = apply_filters(parse_feed(text), feed["include_regex"], feed["exclude_regex"])
    matched = len(items)
    new = [
        it for it in items
        if dry_run or not crud.item_exists(feed["id"], it["guid"], it["infohash"])
    ]
    return new[: settings.max_items_per_run], matched


def process_feed(feed: dict, *, dry_run: bool = False) -> dict:
    """Fetch one feed, push new items to CD2. Returns a summary dict."""
    feed_id = feed["id"]
    summary = {"feed": feed["name"], "found": 0, "new": 0, "pushed": 0, "failed": 0, "skipped": 0}

    try:
        if onelou.is_onelou(feed):
            items, matched = onelou.fetch_new_items(
                feed, dry_run=dry_run, cap=settings.max_items_per_run
            )
        else:
            items, matched = _collect_rss(feed, dry_run)
    except FetchError as exc:
        crud.mark_feed_checked(feed_id, f"error: {exc}")
        summary["error"] = str(exc)
        log.warning("Feed '%s' fetch failed: %s", feed["name"], exc)
        return summary

    summary["found"] = matched
    summary["new"] = len(items)

    if not dry_run:
        for item in items:
            # An item that arrived without a download URL failed to resolve
            # (e.g. cookie expired / non-torrent attachment) — record & move on.
            if not item.get("download"):
                crud.record_item(feed_id, item, "failed", item.get("error", "no download link"))
                summary["failed"] += 1
                continue
            try:
                location = _plan_location(feed, item)
                _dispatch(feed, item["download"], location)
                crud.record_item(feed_id, item, "ok")
                summary["pushed"] += 1
            except Exception as exc:  # noqa: BLE001
                crud.record_item(feed_id, item, "failed", str(exc))
                summary["failed"] += 1
                log.warning("Push failed for '%s': %s", item.get("title"), exc)

    status = "preview" if dry_run else f"ok: +{summary['pushed']} new"
    if summary["failed"]:
        status += f", {summary['failed']} failed"
    if not dry_run:
        crud.mark_feed_checked(feed_id, status)
        try:
            notify.notify_feed_result(feed["name"], summary)
        except Exception as exc:  # noqa: BLE001
            log.warning("notify failed: %s", exc)
    log.info("Feed '%s': %s", feed["name"], summary)
    return summary


def _tick() -> None:
    """Run all feeds whose interval has elapsed."""
    try:
        feeds = crud.list_feeds()
    except Exception as exc:  # noqa: BLE001
        log.error("tick: could not list feeds: %s", exc)
        return
    current = now()
    for feed in feeds:
        if not feed["enabled"]:
            continue
        due = current - feed["last_checked"] >= feed["interval_minutes"] * 60
        if due:
            process_feed(feed)


def run_feed_now(feed_id: int, *, dry_run: bool = False) -> dict | None:
    feed = crud.get_feed(feed_id)
    if not feed:
        return None
    return process_feed(feed, dry_run=dry_run)


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    # coalesce + max_instances=1 so a slow run never overlaps itself.
    _scheduler.add_job(
        _tick, "interval", seconds=60, id="tick",
        coalesce=True, max_instances=1, misfire_grace_time=300,
    )
    _scheduler.start()
    log.info("Scheduler started (tick every 60s)")


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
