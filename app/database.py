"""Thin SQLite layer. Synchronous and tiny — traffic is low, robustness wins."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from .config import settings

_local = threading.local()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """One connection per thread (scheduler + request threads each get their own)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _local.conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'cd2',
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS feeds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'auto',
    interval_minutes INTEGER NOT NULL DEFAULT 30,
    include_regex   TEXT NOT NULL DEFAULT '',
    exclude_regex   TEXT NOT NULL DEFAULT '',
    target_id       INTEGER REFERENCES targets(id) ON DELETE SET NULL,
    target_folder   TEXT NOT NULL DEFAULT '/',
    cookie          TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_checked    REAL NOT NULL DEFAULT 0,
    last_status     TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id     INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid        TEXT NOT NULL,
    infohash    TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    link        TEXT NOT NULL DEFAULT '',
    magnet      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    UNIQUE(feed_id, guid)
);

CREATE INDEX IF NOT EXISTS idx_items_feed ON items(feed_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_infohash ON items(infohash);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Lightweight migration: add columns introduced after first release.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(feeds)")}
        if "cookie" not in cols:
            conn.execute("ALTER TABLE feeds ADD COLUMN cookie TEXT NOT NULL DEFAULT ''")
        if "target_id" not in cols:
            conn.execute("ALTER TABLE feeds ADD COLUMN target_id INTEGER")


def now() -> float:
    return time.time()
