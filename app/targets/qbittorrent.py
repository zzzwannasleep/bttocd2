"""qBittorrent target (Web API v2)."""
from __future__ import annotations

import httpx

from .base import Target, TargetError, as_urls


class QbTarget(Target):
    def _client(self) -> httpx.Client:
        base = (self.config.get("url") or "").rstrip("/")
        if not base:
            raise TargetError("qBittorrent target needs a Web UI url")
        client = httpx.Client(base_url=base, timeout=30, headers={"Referer": base})
        user = self.config.get("username") or ""
        pwd = self.config.get("password") or ""
        if user:
            try:
                r = client.post("/api/v2/auth/login", data={"username": user, "password": pwd})
            except Exception as exc:  # noqa: BLE001
                client.close()
                raise TargetError(f"qBittorrent unreachable: {exc}") from exc
            if r.text.strip() != "Ok.":
                client.close()
                raise TargetError("qBittorrent login failed (check user/password/host whitelist)")
        return client

    def add(self, urls, location: str = "") -> None:
        items = as_urls(urls)
        if not items:
            raise TargetError("no URLs to add")
        client = self._client()
        try:
            data = {"urls": "\n".join(items)}
            loc = location or self.config.get("savepath") or ""
            if loc:
                data["savepath"] = loc
            category = self.config.get("category") or ""
            if category:
                data["category"] = category
            r = client.post("/api/v2/torrents/add", data=data)
            if r.status_code != 200 or r.text.strip().lower() == "fails.":
                raise TargetError(f"qBittorrent add failed (HTTP {r.status_code}: {r.text[:120]})")
        finally:
            client.close()

    def check(self) -> tuple[bool, str]:
        try:
            client = self._client()
            try:
                ver = client.get("/api/v2/app/version")
                return True, f"connected ({ver.text.strip()})" if ver.status_code == 200 else "connected"
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
