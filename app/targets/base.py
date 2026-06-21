"""Target abstraction: a destination that accepts magnet/torrent URLs.

Each downloader/netdisk is a Target subclass implementing add() + check(). The
scheduler resolves a feed's chosen target and calls add(); the UI calls check()
to probe connectivity. New backends only need a new subclass + registry entry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class TargetError(Exception):
    pass


def as_urls(urls) -> list[str]:
    """Normalize a string (possibly newline-joined) or list into a URL list."""
    if isinstance(urls, str):
        parts = urls.replace("\r", "\n").split("\n")
    else:
        parts = list(urls)
    return [u.strip() for u in parts if u and u.strip()]


class Target(ABC):
    def __init__(self, config: dict | None):
        self.config = config or {}

    @abstractmethod
    def add(self, urls, location: str = "") -> None:
        """Submit one or more magnet/torrent URLs. Raise TargetError on failure."""

    @abstractmethod
    def check(self) -> tuple[bool, str]:
        """Probe connectivity. Return (ok, message)."""
