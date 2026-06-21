"""CloudDrive2 offline-download target (gRPC AddOfflineFiles)."""
from __future__ import annotations

import logging
import threading

from .base import Target, TargetError, as_urls

log = logging.getLogger(__name__)

# Cache CloudDriveClient instances by connection so we don't re-login every push.
_clients: dict[tuple, object] = {}
_lock = threading.Lock()


def _key(config: dict) -> tuple:
    return (config.get("url", ""), config.get("username", ""))


def _build(config: dict, *, force: bool = False):
    url = config.get("url", "")
    user = config.get("username", "")
    pwd = config.get("password", "")
    if not (url and user and pwd):
        raise TargetError("CD2 target needs url + username + password")
    key = _key(config)
    with _lock:
        client = _clients.get(key)
        if client is None or force:
            try:
                from clouddrive import CloudDriveClient
            except ImportError as exc:  # pragma: no cover
                raise TargetError("`clouddrive` package not installed") from exc
            log.info("Connecting to CloudDrive2 at %s", url)
            client = _clients[key] = CloudDriveClient(url, user, pwd)
        return client


def _call_add(client, urls: str, to_folder: str):
    payload = {"urls": urls, "toFolder": to_folder, "checkFolderAfterSecs": 0}
    method = getattr(client, "AddOfflineFiles", None)
    if method is None:
        raise TargetError("clouddrive client has no AddOfflineFiles")
    try:
        return method(payload)
    except TypeError:
        from clouddrive.proto import CloudDrive_pb2 as pb  # type: ignore

        return method(pb.AddOfflineFileRequest(urls=urls, toFolder=to_folder, checkFolderAfterSecs=0))


class CD2Target(Target):
    def add(self, urls, location: str = "") -> None:
        joined = "\n".join(as_urls(urls))
        if not joined:
            raise TargetError("no URLs to add")
        folder = location or self.config.get("folder") or "/"
        last: Exception | None = None
        for attempt in range(2):  # retry once with a fresh client (token expiry)
            try:
                client = _build(self.config, force=(attempt == 1))
                result = _call_add(client, joined, folder)
                if not getattr(result, "success", True):
                    msg = getattr(result, "errorMessage", "") or getattr(result, "error_message", "")
                    raise TargetError(f"CD2 rejected task: {msg}")
                return
            except TargetError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                log.warning("CD2 add attempt %d failed: %s", attempt + 1, exc)
        raise TargetError(f"AddOfflineFiles failed: {last}")

    def check(self) -> tuple[bool, str]:
        try:
            _build(self.config, force=True)
            return True, "connected"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
