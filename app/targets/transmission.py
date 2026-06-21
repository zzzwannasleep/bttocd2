"""Transmission target (RPC). Handles the X-Transmission-Session-Id handshake."""
from __future__ import annotations

import httpx

from .base import Target, TargetError, as_urls


class TransmissionTarget(Target):
    def _rpc(self, method: str, arguments: dict) -> dict:
        url = (self.config.get("url") or "").strip()
        if not url:
            raise TargetError("Transmission target needs an RPC url "
                              "(e.g. http://host:9091/transmission/rpc)")
        user = self.config.get("username") or ""
        pwd = self.config.get("password") or ""
        auth = (user, pwd) if user else None
        body = {"method": method, "arguments": arguments}
        headers: dict[str, str] = {}
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(url, json=body, auth=auth, headers=headers)
                if r.status_code == 409:  # session-id handshake
                    headers["X-Transmission-Session-Id"] = r.headers.get("X-Transmission-Session-Id", "")
                    r = client.post(url, json=body, auth=auth, headers=headers)
        except Exception as exc:  # noqa: BLE001
            raise TargetError(f"Transmission unreachable: {exc}") from exc
        if r.status_code == 401:
            raise TargetError("Transmission auth failed (check username/password)")
        if r.status_code != 200:
            raise TargetError(f"Transmission HTTP {r.status_code}")
        data = r.json()
        if data.get("result") != "success":
            raise TargetError(f"Transmission error: {data.get('result')}")
        return data

    def add(self, urls, location: str = "") -> None:
        items = as_urls(urls)
        if not items:
            raise TargetError("no URLs to add")
        loc = location or self.config.get("download_dir") or ""
        for magnet in items:
            args: dict = {"filename": magnet}
            if loc:
                args["download-dir"] = loc
            self._rpc("torrent-add", args)

    def check(self) -> tuple[bool, str]:
        try:
            self._rpc("session-get", {})
            return True, "connected"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
