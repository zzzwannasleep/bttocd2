"""Database access for feeds and processed items."""
from __future__ import annotations

import sqlite3
from typing import Any

from .database import get_conn, now


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


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


def create_feed(data: dict[str, Any]) -> dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO feeds
               (name, url, kind, interval_minutes, include_regex, exclude_regex,
                target_folder, enabled, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                data["name"],
                data["url"],
                data.get("kind", "auto"),
                int(data["interval_minutes"]),
                data.get("include_regex", ""),
                data.get("exclude_regex", ""),
                data.get("target_folder", "/"),
                1 if data.get("enabled", True) else 0,
                now(),
            ),
        )
        feed_id = cur.lastrowid
    return get_feed(feed_id)  # type: ignore[return-value]


def update_feed(feed_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    fields = [
        "name", "url", "kind", "interval_minutes", "include_regex",
        "exclude_regex", "target_folder", "enabled",
    ]
    sets, vals = [], []
    for f in fields:
        if f in data:
            sets.append(f"{f}=?")
            v = data[f]
            if f == "enabled":
                v = 1 if v else 0
            if f == "interval_minutes":
                v = int(v)
            vals.append(v)
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
               (feed_id, guid, infohash, title, link, magnet, status, error, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                feed_id,
                item.get("guid", ""),
                item.get("infohash", ""),
                item.get("title", "")[:500],
                item.get("link", "")[:1000],
                item.get("magnet", "")[:2000],
                status,
                error[:1000],
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


def counts() -> dict[str, int]:
    with get_conn() as conn:
        feeds = conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
        ok = conn.execute("SELECT COUNT(*) FROM items WHERE status='ok'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM items WHERE status='failed'").fetchone()[0]
    return {"feeds": feeds, "pushed": ok, "failed": failed}
