"""Emby/Jellyfin renaming engine with ${var} placeholders + custom keyword tags.

Template syntax follows ani-rss: ${title}, ${seasonFormat}, ${episodeFormat}, etc.
On top of the built-in variables, users define their own keyword rules, e.g.
"CHS / 简体 → 简体中文" exposed as ${lang}. A rule matches if any of its keywords
appears (case-insensitive) in the original release title; the first matching rule
(in list order) for a given variable wins.

A template may contain '/' to also describe the folder layout, e.g.
    ${title} (${year})/Season ${seasonFormat}/${title} - S${seasonFormat}E${episodeFormat}
Each path component is sanitized individually.
"""
from __future__ import annotations

import re

DEFAULT_TEMPLATE = "${title} (${year})/Season ${seasonFormat}/${title} - S${seasonFormat}E${episodeFormat}"

_VAR = re.compile(r"\$\{(\w+)\}")
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')
_SUBGROUP = re.compile(r"^\s*[\[【]([^\]】]+)[\]】]")
_RESOLUTION = re.compile(r"(2160p|1080p|720p|480p|4k)", re.I)
_SOURCE = re.compile(r"(WEB-DL|WEBRip|BluRay|BDRip|HDTV|Remux|WEB)", re.I)


def sanitize(name: str) -> str:
    return _ILLEGAL.sub("", str(name or "")).strip().rstrip(".")


def _fmt_episode(ep: float) -> str:
    return f"{int(ep):02d}" if float(ep).is_integer() else f"{ep:05.1f}"


def _ep_plain(ep: float) -> str:
    return str(int(ep)) if float(ep).is_integer() else str(ep)


def parse_subgroup(title: str) -> str:
    m = _SUBGROUP.search(title or "")
    return m.group(1).strip() if m else ""


def parse_resolution(title: str) -> str:
    m = _RESOLUTION.search(title or "")
    if not m:
        return ""
    val = m.group(1).lower()
    return "2160p" if val == "4k" else val


def parse_source(title: str) -> str:
    m = _SOURCE.search(title or "")
    return m.group(1) if m else ""


def resolve_tags(item_title: str, tags: list[dict] | None) -> dict[str, str]:
    """Resolve user keyword rules into {var: label}.

    `tags` is a flat list of {var, label, patterns:[...]}. First matching rule per
    var wins; every referenced var defaults to '' so unmatched ${var} renders empty.
    """
    out: dict[str, str] = {}
    text = (item_title or "").lower()
    for rule in tags or []:
        var = (rule.get("var") or "").strip()
        if not var:
            continue
        out.setdefault(var, "")  # ensure the var exists (empty by default)
        if out[var]:
            continue  # already matched a higher-priority rule
        patterns = rule.get("patterns") or []
        if any(p and str(p).lower() in text for p in patterns):
            out[var] = rule.get("label", "") or ""
    return out


def resolve_context(meta: dict, season: int, episode: float, item_title: str,
                    tags: list[dict] | None = None) -> dict[str, str]:
    season = int(season or 1)
    title = meta.get("title") or meta.get("title_cn") or meta.get("name") or "Unknown"
    ctx = {
        "title": title,
        "title_cn": meta.get("title_cn") or title,
        "jpTitle": meta.get("original_title") or "",
        "originalTitle": meta.get("original_title") or "",
        "year": str(meta.get("year") or ""),
        "season": str(season),
        "seasonFormat": f"{season:02d}",
        "episode": _ep_plain(episode),
        "episodeFormat": _fmt_episode(episode),
        "subgroup": parse_subgroup(item_title),
        "resolution": parse_resolution(item_title),
        "source": parse_source(item_title),
        "itemTitle": item_title or "",
        "tmdbid": meta.get("meta_id", "") if meta.get("meta_source") == "tmdb" else "",
        "bgmId": meta.get("meta_id", "") if meta.get("meta_source") == "bangumi" else "",
    }
    ctx.update(resolve_tags(item_title, tags))
    return ctx


def render(template: str, ctx: dict[str, str]) -> str:
    out = _VAR.sub(lambda m: str(ctx.get(m.group(1), "")), template or DEFAULT_TEMPLATE)
    out = out.replace("()", "").replace("[]", "").replace("【】", "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    # tidy each path component: trim spaces and dangling separators
    parts = []
    for p in out.split("/"):
        p = p.strip().strip("-").strip()
        parts.append(p)
    return "/".join(parts)


def build(template: str, ctx: dict[str, str]) -> dict:
    """Return {'folder', 'filename', 'full'} (relative, sanitized)."""
    rendered = render(template, ctx)
    parts = [sanitize(p) for p in rendered.split("/") if p.strip()]
    parts = [p for p in parts if p]
    if not parts:
        parts = [sanitize(f"{ctx.get('title','Unknown')} - S{ctx.get('seasonFormat','01')}E{ctx.get('episodeFormat','01')}")]
    return {"folder": "/".join(parts[:-1]), "filename": parts[-1], "full": "/".join(parts)}


def preview(meta: dict, season: int, episode: float, item_title: str,
            template: str | None = None, tags: list[dict] | None = None, ext: str = "mkv") -> str:
    ctx = resolve_context(meta, season, episode, item_title, tags)
    return build(template or DEFAULT_TEMPLATE, ctx)["full"] + f".{ext}"
