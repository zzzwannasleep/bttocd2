"""Database access for targets, feeds and processed items."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import targets as targets_mod
from .config import settings
from .database import get_conn, now


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #
def _target_dict(r: sqlite3.Row, *, mask: bool) -> dict[str, Any]:
    d = dict(r)
    config = json.loads(d.pop("config_json", "{}") or "{}")
    if mask:
        secrets = targets_mod.secret_keys(d["type"])
        masked = {}
        for k, v in config.items():
            if k in secrets:
                masked["has_" + k] = bool(v)
            else:
                masked[k] = v
        config = masked
    d["config"] = config
    return d


def list_targets(*, mask: bool = True) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM targets ORDER BY id").fetchall()
    return [_target_dict(r, mask=mask) for r in rows]


def get_target(target_id: int, *, mask: bool = True) -> dict[str, Any] | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM targets WHERE id=?", (target_id,)).fetchone()
    return _target_dict(r, mask=mask) if r else None


def create_target(data: dict[str, Any]) -> dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO targets (name, type, config_json, enabled, created_at) VALUES (?,?,?,?,?)",
            (data["name"], data["type"], json.dumps(data.get("config", {})),
             1 if data.get("enabled", True) else 0, now()),
        )
        tid = cur.lastrowid
    return get_target(tid)  # type: ignore[return-value]


def update_target(target_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_target(target_id, mask=False)
    if not existing:
        return None
    ttype = data.get("type", existing["type"])
    # Merge config: a blank secret field means "keep the stored value".
    new_config = dict(existing["config"])
    incoming = data.get("config", {})
    secrets = targets_mod.secret_keys(ttype)
    for k, v in incoming.items():
        if k in secrets and (v is None or v == ""):
            continue  # keep existing secret
        new_config[k] = v
    with get_conn() as conn:
        conn.execute(
            "UPDATE targets SET name=?, type=?, config_json=?, enabled=? WHERE id=?",
            (data.get("name", existing["name"]), ttype, json.dumps(new_config),
             1 if data.get("enabled", existing["enabled"]) else 0, target_id),
        )
    return get_target(target_id)


def delete_target(target_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM targets WHERE id=?", (target_id,))


def seed_default_target() -> None:
    """On first run, create a CD2 target from env and attach orphan feeds to it."""
    with get_conn() as conn:
        if conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0] > 0:
            return
        if not (settings.cd2_username and settings.cd2_password):
            return
        config = {
            "url": settings.cd2_url,
            "username": settings.cd2_username,
            "password": settings.cd2_password,
            "folder": settings.default_target_folder,
        }
        cur = conn.execute(
            "INSERT INTO targets (name, type, config_json, enabled, created_at) VALUES (?,?,?,?,?)",
            ("CloudDrive2", "cd2", json.dumps(config), 1, now()),
        )
        conn.execute("UPDATE feeds SET target_id=? WHERE target_id IS NULL", (cur.lastrowid,))


# --------------------------------------------------------------------------- #
# Feeds
# --------------------------------------------------------------------------- #
def list_feeds() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM feeds ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_feed(feed_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        return _row(conn.execute("SELECT * FROM feeds WHERE id=?", (feed_id,)).fetchone())


# Writable feed columns and their default value when creating.
_FEED_DEFAULTS: dict[str, Any] = {
    "name": "", "url": "", "kind": "auto", "interval_minutes": 30,
    "include_regex": "", "exclude_regex": "", "target_id": None,
    "target_folder": "/", "cookie": "",
    "title_cn": "", "original_title": "", "year": "", "season": 1,
    "episode_offset": 0, "total_episodes": 0, "poster": "",
    "meta_source": "", "meta_id": "", "library_path": "",
    "rename_enabled": 0, "rename_template": "", "enabled": 1,
}
_FEED_INT = {"interval_minutes", "season", "episode_offset", "total_episodes"}
_FEED_BOOL = {"enabled", "rename_enabled"}


def _coerce_feed_value(field: str, value: Any) -> Any:
    if field in _FEED_BOOL:
        return 1 if value else 0
    if field == "target_id":
        return int(value) if value not in (None, "") else None
    if field in _FEED_INT:
        try:
            return int(value)
        except (TypeError, ValueError):
            return _FEED_DEFAULTS[field]
    return value


def create_feed(data: dict[str, Any]) -> dict[str, Any]:
    row = {f: _coerce_feed_value(f, data.get(f, default)) for f, default in _FEED_DEFAULTS.items()}
    cols = list(row.keys()) + ["created_at"]
    vals = list(row.values()) + [now()]
    placeholders = ",".join("?" * len(cols))
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO feeds ({','.join(cols)}) VALUES ({placeholders})", vals
        )
        feed_id = cur.lastrowid
    return get_feed(feed_id)  # type: ignore[return-value]


def update_feed(feed_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    sets, vals = [], []
    for field in _FEED_DEFAULTS:
        if field in data:
            sets.append(f"{field}=?")
            vals.append(_coerce_feed_value(field, data[field]))
    if not sets:
        return get_feed(feed_id)
    vals.append(feed_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE feeds SET {', '.join(sets)} WHERE id=?", vals)
    return get_feed(feed_id)


def delete_feed(feed_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM feeds WHERE id=?", (feed_id,))


def mark_feed_checked(feed_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE feeds SET last_checked=?, last_status=? WHERE id=?",
            (now(), status[:500], feed_id),
        )


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
def item_exists(feed_id: int, guid: str, infohash: str = "") -> bool:
    with get_conn() as conn:
        if conn.execute(
            "SELECT 1 FROM items WHERE feed_id=? AND guid=? LIMIT 1", (feed_id, guid)
        ).fetchone():
            return True
        if infohash:
            # Dedup across feeds by infohash so the same release isn't pushed twice.
            if conn.execute(
                "SELECT 1 FROM items WHERE infohash=? AND status IN ('ok','pending') LIMIT 1",
                (infohash,),
            ).fetchone():
                return True
    return False


def record_item(feed_id: int, item: dict[str, Any], status: str, error: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO items
               (feed_id, guid, infohash, title, link, magnet, status, error, dest, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                feed_id,
                item.get("guid", ""),
                item.get("infohash", ""),
                item.get("title", "")[:500],
                item.get("link", "")[:1000],
                item.get("magnet", "")[:2000],
                status,
                error[:1000],
                item.get("dest", "")[:1000],
                now(),
            ),
        )


def list_items(feed_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 1000))
    with get_conn() as conn:
        if feed_id:
            rows = conn.execute(
                "SELECT * FROM items WHERE feed_id=? ORDER BY created_at DESC LIMIT ?",
                (feed_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM items ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Rename jobs (qBittorrent file-rename watcher)
# --------------------------------------------------------------------------- #
def enqueue_rename(target_id: int, infohash: str, new_name: str, title: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO rename_jobs (target_id, infohash, new_name, title, status, created_at)
               VALUES (?,?,?,?, 'pending', ?)
               ON CONFLICT(target_id, infohash) DO NOTHING""",
            (target_id, infohash.lower(), new_name, title[:300], now()),
        )


def pending_rename_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rename_jobs WHERE status='pending' ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def finish_rename_job(job_id: int, status: str, error: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE rename_jobs SET status=?, last_error=?, attempts=attempts+1 WHERE id=?",
            (status, error[:300], job_id),
        )


def bump_rename_attempt(job_id: int, error: str, max_attempts: int) -> None:
    """Increment attempts; mark failed once the cap is reached."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE rename_jobs
               SET attempts=attempts+1, last_error=?,
                   status=CASE WHEN attempts+1 >= ? THEN 'failed' ELSE 'pending' END
               WHERE id=?""",
            (error[:300], max_attempts, job_id),
        )


def counts() -> dict[str, int]:
    with get_conn() as conn:
        feeds = conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
        ok = conn.execute("SELECT COUNT(*) FROM items WHERE status='ok'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM items WHERE status='failed'").fetchone()[0]
    return {"feeds": feeds, "pushed": ok, "failed": failed}
