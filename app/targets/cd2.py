"""CloudDrive2 target — talks to CD2's gRPC API directly via vendored stubs.

We dropped the third-party `clouddrive` PyPI package (removed from PyPI) and
generate our own client from the official clouddrive.proto (see app/cd2proto).

Auth: GetToken(userName,password) -> JWT, attached as `authorization: Bearer …`
metadata on every call; refreshed once on UNAUTHENTICATED.
"""
from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse

import grpc

from ..cd2proto import clouddrive_pb2 as pb
from ..cd2proto import clouddrive_pb2_grpc as pbg
from .base import Target, TargetError, as_urls

log = logging.getLogger(__name__)

_sessions: dict[tuple, "_Session"] = {}
_lock = threading.Lock()


def _host_port(url: str) -> str:
    u = urlparse(url if "://" in url else "http://" + url)
    return f"{u.hostname or '127.0.0.1'}:{u.port or 19798}"


class _Session:
    def __init__(self, url: str, user: str, pwd: str):
        self.target = _host_port(url)
        self.user, self.pwd = user, pwd
        self.channel = grpc.insecure_channel(self.target)
        self.stub = pbg.CloudDriveFileSrvStub(self.channel)
        self.token: str | None = None

    def _login(self) -> None:
        res = self.stub.GetToken(pb.GetTokenRequest(userName=self.user, password=self.pwd), timeout=30)
        if not res.success:
            raise TargetError(res.errorMessage or "GetToken failed (check CD2 account)")
        self.token = res.token

    def _metadata(self):
        if not self.token:
            self._login()
        return (("authorization", f"Bearer {self.token}"),)

    def call(self, method: str, request, *, stream: bool = False, timeout: int = 60):
        fn = getattr(self.stub, method)
        for attempt in range(2):
            try:
                if stream:
                    return list(fn(request, metadata=self._metadata(), timeout=timeout))
                return fn(request, metadata=self._metadata(), timeout=timeout)
            except grpc.RpcError as exc:
                if exc.code() == grpc.StatusCode.UNAUTHENTICATED and attempt == 0:
                    self.token = None  # refresh and retry once
                    continue
                raise TargetError(f"CD2 {method} failed: {exc.code().name} {exc.details()}") from exc


def _get_session(config: dict, *, force: bool = False) -> _Session:
    url = config.get("url", "")
    user = config.get("username", "")
    pwd = config.get("password", "")
    if not (url and user and pwd):
        raise TargetError("CD2 target needs url + username + password")
    key = (_host_port(url), user)
    with _lock:
        sess = _sessions.get(key)
        if sess is None or force:
            log.info("Connecting to CloudDrive2 at %s", key[0])
            sess = _sessions[key] = _Session(url, user, pwd)
        return sess


class CD2Target(Target):
    def _session(self, force: bool = False) -> _Session:
        return _get_session(self.config, force=force)

    def add(self, urls, location: str = "") -> None:
        joined = "\n".join(as_urls(urls))
        if not joined:
            raise TargetError("no URLs to add")
        folder = location or self.config.get("folder") or "/"
        req = pb.AddOfflineFileRequest(urls=joined, toFolder=folder, checkFolderAfterSecs=0)
        res = self._session().call("AddOfflineFiles", req)
        if not getattr(res, "success", True):
            raise TargetError(f"CD2 rejected task: {getattr(res, 'errorMessage', '')}")

    def check(self) -> tuple[bool, str]:
        try:
            self._session(force=True)._login()
            return True, "connected"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    # ---- file operations (used by the rename watcher) ---- #
    def list_files(self, folder: str) -> list[dict]:
        req = pb.ListSubFileRequest(path=folder, forceRefresh=False)
        replies = self._session().call("GetSubFiles", req, stream=True)
        out: list[dict] = []
        for reply in replies:
            for f in reply.subFiles:
                out.append({
                    "name": f.name,
                    "path": f.fullPathName or f"{folder.rstrip('/')}/{f.name}",
                    "is_dir": bool(f.isDirectory),
                    "size": int(f.size or 0),
                })
        return out

    def rename_path(self, file_path: str, new_name: str) -> None:
        req = pb.RenameFileRequest(theFilePath=file_path, newName=new_name)
        res = self._session().call("RenameFile", req)
        if not getattr(res, "success", True):
            raise TargetError(getattr(res, "errorMessage", "") or "RenameFile failed")

    def move_path(self, file_path: str, dest_folder: str) -> None:
        req = pb.MoveFileRequest(theFilePaths=[file_path], destPath=dest_folder)
        res = self._session().call("MoveFile", req)
        if not getattr(res, "success", True):
            raise TargetError(getattr(res, "errorMessage", "") or "MoveFile failed")
