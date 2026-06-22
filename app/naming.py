"""Emby/Jellyfin-friendly naming for renamed episodes.

Builds a relative path like:
    进击的巨人 (2013)/Season 04/进击的巨人 - S04E28
from subscription metadata + season + (offset-adjusted) episode number.

Emby/Jellyfin recognise `Show (Year)/Season NN/Show - SNNENN.ext`.
"""
from __future__ import annotations

import re

DEFAULT_TEMPLATE = "{title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d}"

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def sanitize(name: str) -> str:
    """Strip filesystem-illegal characters from a single path component."""
    return _ILLEGAL.sub("", str(name or "")).strip().rstrip(".") or "unknown"


def _fmt_episode(ep: float) -> str:
    return f"{int(ep):02d}" if float(ep).is_integer() else f"{ep:05.1f}"


def build(meta: dict, season: int, episode: float, template: str | None = None) -> dict:
    """Return {'folder': rel_dir, 'filename': name_without_ext, 'full': rel_path}.

    `meta` should carry 'title' (display) and 'year'. Path components are
    sanitized individually so a '/' in the template stays a real separator.
    """
    title = sanitize(meta.get("title") or meta.get("title_cn") or meta.get("name") or "Unknown")
    year = meta.get("year") or ""
    season = int(season or 1)
    tmpl = template or DEFAULT_TEMPLATE
    try:
        rendered = tmpl.format(
            title=title, year=year, season=season,
            episode=int(episode) if float(episode).is_integer() else episode,
        )
    except (KeyError, ValueError):
        rendered = DEFAULT_TEMPLATE.format(title=title, year=year, season=season, episode=int(episode))
    # year may be empty -> tidy up "Title ()"
    rendered = rendered.replace(" ()", "")
    parts = [sanitize(p) for p in rendered.split("/") if p.strip()]
    filename = parts[-1] if parts else f"{title} - S{season:02d}E{_fmt_episode(episode)}"
    folder = "/".join(parts[:-1])
    full = "/".join(parts)
    return {"folder": folder, "filename": filename, "full": full}


def preview(meta: dict, season: int, episode: float, ext: str = "mkv", template: str | None = None) -> str:
    return build(meta, season, episode, template)["full"] + f".{ext}"
