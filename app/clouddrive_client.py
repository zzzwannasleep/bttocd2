"""Wrapper around the `clouddrive` gRPC client for offline downloads.

Isolated here so the rest of the app never touches the gRPC API directly.
If the upstream `clouddrive` package changes a signature, this is the only
file to adjust.

CloudDrive2 RPC used:  AddOfflineFiles(AddOfflineFileRequest{urls, toFolder, checkFolderAfterSecs})
"""
from __future__ import annotations

import logging
import threading

from .config import settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_client = None  # lazily constructed CloudDriveClient


class CloudDriveError(Exception):
    pass


def _build_client():
    if not settings.cd2_username or not settings.cd2_password:
        raise CloudDriveError("CD2_USERNAME / CD2_PASSWORD not configured")
    try:
        from clouddrive import CloudDriveClient  # imported lazily so the app can boot without it
    except ImportError as exc:  # pragma: no cover
        raise CloudDriveError(
            "`clouddrive` package not installed. Add it to requirements.txt."
        ) from exc
    log.info("Connecting to CloudDrive2 at %s", settings.cd2_url)
    return CloudDriveClient(settings.cd2_url, settings.cd2_username, settings.cd2_password)


def _get_client(force_new: bool = False):
    global _client
    with _lock:
        if _client is None or force_new:
            _client = _build_client()
        return _client


def _call_add(client, urls: str, to_folder: str) -> object:
    """Invoke AddOfflineFiles, tolerating dict- or kwargs-style packages."""
    payload = {"urls": urls, "toFolder": to_folder, "checkFolderAfterSecs": 0}
    method = getattr(client, "AddOfflineFiles", None)
    if method is None:
        raise CloudDriveError("clouddrive client has no AddOfflineFiles method")
    try:
        return method(payload)
    except TypeError:
        # Some builds expect a constructed request message instead of a dict.
        from clouddrive.proto import CloudDrive_pb2 as pb  # type: ignore

        return method(pb.AddOfflineFileRequest(urls=urls, toFolder=to_folder, checkFolderAfterSecs=0))


def add_offline(urls: str, to_folder: str) -> None:
    """Push one or more magnet/torrent URLs (newline-separated) to CD2.

    Raises CloudDriveError on failure.
    """
    to_folder = to_folder or settings.default_target_folder
    last_exc: Exception | None = None
    for attempt in range(2):  # retry once with a fresh client (token may have expired)
        try:
            client = _get_client(force_new=(attempt == 1))
            result = _call_add(client, urls, to_folder)
            # FileOperationResult has .success / .errorMessage when present.
            success = getattr(result, "success", True)
            if not success:
                msg = getattr(result, "errorMessage", "") or getattr(result, "error_message", "")
                raise CloudDriveError(f"CD2 rejected task: {msg}")
            return
        except CloudDriveError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize transport errors
            last_exc = exc
            log.warning("AddOfflineFiles attempt %d failed: %s", attempt + 1, exc)
    raise CloudDriveError(f"AddOfflineFiles failed: {last_exc}")


def check_connection() -> tuple[bool, str]:
    """Best-effort connectivity probe for the status panel."""
    try:
        _get_client(force_new=True)
        return True, "connected"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
