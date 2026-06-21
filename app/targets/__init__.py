"""Target registry + factory. Add a new downloader by registering it here."""
from __future__ import annotations

from .base import Target, TargetError, as_urls
from .cd2 import CD2Target
from .qbittorrent import QbTarget
from .transmission import TransmissionTarget

REGISTRY: dict[str, type[Target]] = {
    "cd2": CD2Target,
    "qbittorrent": QbTarget,
    "transmission": TransmissionTarget,
}

# UI metadata: which config fields each target type needs, and how its
# per-feed "location" is labelled. `secret: True` fields are masked in the API.
TYPES = [
    {
        "type": "cd2",
        "label": "CloudDrive2 离线",
        "fields": [
            {"key": "url", "label": "地址", "placeholder": "http://host.docker.internal:19798"},
            {"key": "username", "label": "CD2 账号"},
            {"key": "password", "label": "CD2 密码", "secret": True},
        ],
        "location_label": "网盘文件夹路径",
        "location_placeholder": "/115网盘/离线下载",
    },
    {
        "type": "qbittorrent",
        "label": "qBittorrent",
        "fields": [
            {"key": "url", "label": "Web UI 地址", "placeholder": "http://host:8080"},
            {"key": "username", "label": "账号"},
            {"key": "password", "label": "密码", "secret": True},
            {"key": "category", "label": "分类（可选）", "placeholder": "movies"},
        ],
        "location_label": "保存路径 savepath（可选）",
        "location_placeholder": "/downloads",
    },
    {
        "type": "transmission",
        "label": "Transmission",
        "fields": [
            {"key": "url", "label": "RPC 地址", "placeholder": "http://host:9091/transmission/rpc"},
            {"key": "username", "label": "账号（可选）"},
            {"key": "password", "label": "密码（可选）", "secret": True},
        ],
        "location_label": "下载目录 download-dir（可选）",
        "location_placeholder": "/downloads",
    },
]

_SECRET_KEYS = {
    t["type"]: {f["key"] for f in t["fields"] if f.get("secret")} for t in TYPES
}


def make_target(target_type: str, config: dict) -> Target:
    cls = REGISTRY.get(target_type)
    if cls is None:
        raise TargetError(f"unknown target type: {target_type}")
    return cls(config)


def secret_keys(target_type: str) -> set[str]:
    return _SECRET_KEYS.get(target_type, {"password"})


__all__ = ["Target", "TargetError", "as_urls", "make_target", "TYPES", "REGISTRY", "secret_keys"]
