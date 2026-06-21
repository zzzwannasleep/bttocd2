"""Minimal bencode parser + .torrent -> magnet conversion (pure stdlib).

1lou (and most forums) serve a `.torrent` file, not a magnet. CloudDrive2's
offline API takes URLs (magnets), and the cloud cannot fetch a login-gated
`.torrent` itself — so we download the torrent ourselves and turn it into a
magnet link here: magnet:?xt=urn:btih:<sha1(info)>&dn=<name>&tr=<trackers>.
"""
from __future__ import annotations

import hashlib
from urllib.parse import quote


class TorrentError(Exception):
    pass


def _decode(data: bytes, i: int):
    """Return (object, next_index) for the bencoded value starting at i."""
    ch = data[i : i + 1]
    if ch == b"i":  # integer
        end = data.index(b"e", i)
        return int(data[i + 1 : end]), end + 1
    if ch == b"l":  # list
        i += 1
        out = []
        while data[i : i + 1] != b"e":
            val, i = _decode(data, i)
            out.append(val)
        return out, i + 1
    if ch == b"d":  # dict
        i += 1
        out: dict = {}
        while data[i : i + 1] != b"e":
            key, i = _decode(data, i)
            val, i = _decode(data, i)
            out[key] = val
        return out, i + 1
    if ch.isdigit():  # byte string: <len>:<bytes>
        colon = data.index(b":", i)
        length = int(data[i:colon])
        start = colon + 1
        return data[start : start + length], start + length
    raise TorrentError(f"invalid bencode token at offset {i}")


def _top_dict_with_spans(data: bytes):
    """Decode the top-level dict and capture each value's raw byte span.

    The raw span lets us hash the `info` dict exactly as it appears on the wire,
    which is the correct way to compute the v1 infohash.
    """
    if data[0:1] != b"d":
        raise TorrentError("not a torrent (missing top-level dict)")
    i = 1
    out: dict = {}
    spans: dict = {}
    while data[i : i + 1] != b"e":
        key, i = _decode(data, i)
        start = i
        val, i = _decode(data, i)
        out[key] = val
        spans[key] = (start, i)
    return out, spans


def looks_like_torrent(data: bytes) -> bool:
    return bool(data) and data[:1] == b"d" and b"4:info" in data[:4096]


def torrent_to_magnet(data: bytes) -> tuple[str, str]:
    """Convert raw .torrent bytes to (magnet_uri, display_name).

    Raises TorrentError if the bytes are not a valid torrent (e.g. an HTML
    login page returned because the cookie was missing/expired).
    """
    if not looks_like_torrent(data):
        raise TorrentError("response is not a .torrent file (login/cookie expired?)")
    try:
        meta, spans = _top_dict_with_spans(data)
    except (ValueError, IndexError, TorrentError) as exc:
        raise TorrentError(f"failed to parse torrent: {exc}") from exc

    if b"info" not in spans:
        raise TorrentError("torrent has no info dict")
    start, end = spans[b"info"]
    infohash = hashlib.sha1(data[start:end]).hexdigest()

    info = meta.get(b"info", {})
    name = ""
    if isinstance(info, dict) and isinstance(info.get(b"name"), (bytes, bytearray)):
        name = bytes(info[b"name"]).decode("utf-8", "replace")

    trackers: list[str] = []

    def _add(tr) -> None:
        if isinstance(tr, (bytes, bytearray)):
            s = bytes(tr).decode("utf-8", "replace")
            if s and s not in trackers:
                trackers.append(s)

    _add(meta.get(b"announce"))
    for tier in meta.get(b"announce-list") or []:
        if isinstance(tier, list):
            for tr in tier:
                _add(tr)

    parts = [f"magnet:?xt=urn:btih:{infohash}"]
    if name:
        parts.append("dn=" + quote(name))
    for tr in trackers:
        parts.append("tr=" + quote(tr))
    return "&".join(parts), name
