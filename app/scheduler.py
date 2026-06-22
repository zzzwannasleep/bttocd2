"""Polling scheduler.

A single background "tick" runs every minute, finds feeds that are due, and
processes them sequentially. Sequential processing + per-host rate limiting in
fetcher.py is deliberate: it keeps load on the BT sites low and predictable,
which is the best defense against rate-limit bans.
"""
from __future__ import annotations

import logging
import posixpath
import re

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
    s = appsettings.all_settings()
    meta = {
        "title": feed.get("title_cn") or feed.get("original_title"),
        "title_cn": feed.get("title_cn"),
        "original_title": feed.get("original_title"),
        "year": feed.get("year"),
        "meta_source": feed.get("meta_source"),
        "meta_id": feed.get("meta_id"),
    }
    template = feed.get("rename_template") or s.get("default_rename_template") or None
    ctx = naming.resolve_context(meta, feed.get("season") or 1, ep, item.get("title", ""), s.get("rename_tags"))
    plan = naming.build(template, ctx)
    root = (feed.get("library_path") or s.get("library_root") or "").rstrip("/")
    location = f"{root}/{plan['folder']}" if root else plan["folder"]
    item["dest"] = plan["full"] + ".*"
    item["rename_filename"] = plan["filename"]  # used by the qB rename watcher
    return location


_BTIH_RE = re.compile(r"btih:([0-9a-fA-F]{40})", re.I)


def _infohash_of(urls: str) -> str:
    m = _BTIH_RE.search(urls or "")
    return m.group(1).lower() if m else ""


def _resolve_target(feed: dict) -> dict:
    tid = feed.get("target_id")
    if not tid:
        raise targets_mod.TargetError("该源未配置分发目标")
    target_row = crud.get_target(tid, mask=False)
    if not target_row:
        raise targets_mod.TargetError("分发目标不存在（已被删除？）")
    if not target_row["enabled"]:
        raise targets_mod.TargetError(f"目标「{target_row['name']}」已停用")
    return target_row


def _maybe_enqueue_rename(feed: dict, item: dict, target_row: dict) -> None:
    """For qBittorrent targets with rename enabled, queue a file-rename keyed by
    infohash. The watcher renames as soon as qB has the file list (no need to wait
    for the download to finish — renaming mid-download doesn't affect seeding)."""
    if target_row["type"] != "qbittorrent" or not item.get("rename_filename"):
        return
    infohash = item.get("infohash") or _infohash_of(item.get("download", ""))
    if len(infohash) != 40:
        return  # need a v1 infohash to locate the torrent in qB
    crud.enqueue_rename(target_row["id"], infohash, item["rename_filename"], item.get("title", ""))


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
                target_row = _resolve_target(feed)
                location = _plan_location(feed, item)
                targets_mod.make_target(target_row["type"], target_row["config"]).add(
                    item["download"], location
                )
                crud.record_item(feed_id, item, "ok")
                _maybe_enqueue_rename(feed, item, target_row)
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


# qBittorrent rename watcher ------------------------------------------------- #
_VIDEO_EXT = {".mkv", ".mp4", ".ts", ".avi", ".flv", ".mov", ".wmv", ".m2ts", ".rmvb", ".webm"}
RENAME_MAX_ATTEMPTS = 40  # ~ retries until qB fetches metadata, then give up


def _process_rename_job(job: dict) -> None:
    target_row = crud.get_target(job["target_id"], mask=False)
    if not target_row or target_row["type"] != "qbittorrent":
        crud.finish_rename_job(job["id"], "skipped", "target missing or not qBittorrent")
        return
    target = targets_mod.make_target("qbittorrent", target_row["config"])
    files = target.files(job["infohash"])
    if not files:
        crud.bump_rename_attempt(job["id"], "metadata not ready yet", RENAME_MAX_ATTEMPTS)
        return
    videos = [f for f in files if posixpath.splitext(f.get("name", ""))[1].lower() in _VIDEO_EXT]
    pool = videos or files
    main = max(pool, key=lambda f: f.get("size", 0))
    old = main.get("name", "")
    if not old:
        crud.finish_rename_job(job["id"], "skipped", "no file name from qB")
        return
    ext = posixpath.splitext(old)[1]
    new = job["new_name"] + ext  # place at the save-path root with the Emby name
    if new == old:
        crud.finish_rename_job(job["id"], "done", "already named")
        return
    target.rename_file(job["infohash"], old, new)
    crud.finish_rename_job(job["id"], "done")
    log.info("qB renamed [%s] %s -> %s", job["infohash"][:8], old, new)


def _rename_tick() -> None:
    jobs = crud.pending_rename_jobs()
    for job in jobs:
        try:
            _process_rename_job(job)
        except Exception as exc:  # noqa: BLE001
            crud.bump_rename_attempt(job["id"], str(exc), RENAME_MAX_ATTEMPTS)
            log.warning("rename job %s failed: %s", job["id"], exc)


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
    _scheduler.add_job(
        _rename_tick, "interval", seconds=20, id="rename",
        coalesce=True, max_instances=1, misfire_grace_time=60,
    )
    _scheduler.start()
    log.info("Scheduler started (feed tick 60s, rename watcher 20s)")


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
