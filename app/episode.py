"""Parse an episode number from a release title.

Anime/TV release names are messy. We try a series of patterns in priority order
and avoid false positives like resolution (1080p), year (2023), codec (x264,
10bit). Returns a float (to allow .5 specials) or None.
"""
from __future__ import annotations

import re

# Ordered: most specific / least ambiguous first.
_PATTERNS = [
    re.compile(r"S\d{1,2}E(\d{1,4})", re.I),                 # S01E12
    re.compile(r"第\s*(\d{1,4})(?:\.\d)?\s*[话話集]"),         # 第12话 / 第12集
    re.compile(r"\[(\d{1,3}(?:\.\d)?)(?:v\d)?\]"),            # [12] [12.5] [12v2]  (digits only -> not [1080p])
    re.compile(r"[-–]\s*(\d{1,3}(?:\.\d)?)(?:v\d)?\s*(?:\[|\(|$|·|\s)"),  # Title - 12 [..]
    re.compile(r"\bE(?:P)?\s*(\d{1,4}(?:\.\d)?)\b", re.I),    # E12 / EP12
    re.compile(r"\b(\d{1,3}(?:\.\d)?)(?:v\d)?\s*(?:话|話|集|END|FIN)\b", re.I),  # 12话 / 12 END
]


def parse_episode(title: str) -> float | None:
    if not title:
        return None
    for pat in _PATTERNS:
        m = pat.search(title)
        if m:
            try:
                val = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if 0 <= val < 2000:  # sanity
                return val
    return None


def apply_offset(episode: float, offset: int) -> float:
    """Apply the per-subscription episode offset (can be negative)."""
    return episode + (offset or 0)
