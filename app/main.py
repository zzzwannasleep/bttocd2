"""FastAPI application: login-protected web UI + JSON API."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import httpx

from . import appsettings, crud, meta as meta_mod, notify, scheduler, security, targets as targets_mod
from .config import settings
from .database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("bt2cd2")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    appsettings.load()
    crud.seed_default_target()
    scheduler.start()
    log.info("bt2cd2 started. Web user: %s", settings.web_username)
    yield
    scheduler.shutdown()


app = FastAPI(title="bt2cd2", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def require_login(request: Request) -> str:
    user = security.validate_session(request.cookies.get(security.COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginBody, request: Request, response: Response):
    if not security.verify_login(body.username, body.password, _client_ip(request)):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = security.issue_session(body.username)
    secure = request.url.scheme == "https"
    response.set_cookie(
        security.COOKIE_NAME, token,
        httponly=True, samesite="strict", secure=secure,
        max_age=settings.session_ttl_seconds, path="/",
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(security.COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user: str = Depends(require_login)):
    return {"username": user}


# --------------------------------------------------------------------------- #
# Feeds
# --------------------------------------------------------------------------- #
class FeedBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=4, max_length=1000)
    kind: str = "auto"
    interval_minutes: int = Field(default=settings.default_interval_minutes, ge=5, le=1440)
    include_regex: str = Field(default="", max_length=500)
    exclude_regex: str = Field(default="", max_length=500)
    target_id: int | None = None
    target_folder: str = Field(default="/", max_length=500)
    cookie: str = Field(default="", max_length=8000)
    enabled: bool = True
    # metadata / scraping / rename
    title_cn: str = Field(default="", max_length=300)
    original_title: str = Field(default="", max_length=300)
    year: str = Field(default="", max_length=10)
    season: int = Field(default=1, ge=0, le=99)
    episode_offset: int = Field(default=0, ge=-9999, le=9999)
    total_episodes: int = Field(default=0, ge=0, le=99999)
    poster: str = Field(default="", max_length=1000)
    meta_source: str = Field(default="", max_length=20)
    meta_id: str = Field(default="", max_length=40)
    library_path: str = Field(default="", max_length=500)
    rename_enabled: bool = False
    rename_template: str = Field(default="", max_length=300)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        p = urlparse(v)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError("url must be http(s)")
        return v

    @field_validator("include_regex", "exclude_regex")
    @classmethod
    def _check_regex(cls, v: str) -> str:
        if v:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"invalid regex: {exc}") from exc
        return v


@app.get("/api/feeds")
def get_feeds(user: str = Depends(require_login)):
    return crud.list_feeds()


@app.post("/api/feeds")
def add_feed(body: FeedBody, user: str = Depends(require_login)):
    return crud.create_feed(body.model_dump())


@app.put("/api/feeds/{feed_id}")
def edit_feed(feed_id: int, body: FeedBody, user: str = Depends(require_login)):
    updated = crud.update_feed(feed_id, body.model_dump())
    if not updated:
        raise HTTPException(404, "feed not found")
    return updated


@app.delete("/api/feeds/{feed_id}")
def remove_feed(feed_id: int, user: str = Depends(require_login)):
    crud.delete_feed(feed_id)
    return {"ok": True}


@app.post("/api/feeds/{feed_id}/check")
def check_feed(feed_id: int, user: str = Depends(require_login)):
    result = scheduler.run_feed_now(feed_id, dry_run=False)
    if result is None:
        raise HTTPException(404, "feed not found")
    return result


@app.post("/api/feeds/{feed_id}/preview")
def preview_feed(feed_id: int, user: str = Depends(require_login)):
    result = scheduler.run_feed_now(feed_id, dry_run=True)
    if result is None:
        raise HTTPException(404, "feed not found")
    return result


# --------------------------------------------------------------------------- #
# Items / status
# --------------------------------------------------------------------------- #
@app.get("/api/items")
def get_items(feed_id: int | None = None, limit: int = 200, user: str = Depends(require_login)):
    return crud.list_items(feed_id, limit)


@app.get("/api/status")
def status(user: str = Depends(require_login)):
    targets = crud.list_targets()
    return {
        "counts": crud.counts(),
        "targets": [
            {"id": t["id"], "name": t["name"], "type": t["type"], "enabled": t["enabled"]}
            for t in targets
        ],
        "anti_block": {
            "host_min_interval": settings.host_min_interval,
            "fetch_jitter_seconds": settings.fetch_jitter_seconds,
            "flaresolverr": bool(settings.flaresolverr_url),
            "proxy": bool(settings.http_proxy),
        },
    }


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #
class TargetBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["cd2", "qbittorrent", "transmission"]
    config: dict = Field(default_factory=dict)
    enabled: bool = True


@app.get("/api/target-types")
def target_types(user: str = Depends(require_login)):
    return targets_mod.TYPES


@app.get("/api/targets")
def get_targets(user: str = Depends(require_login)):
    return crud.list_targets()


@app.post("/api/targets")
def add_target(body: TargetBody, user: str = Depends(require_login)):
    return crud.create_target(body.model_dump())


@app.put("/api/targets/{target_id}")
def edit_target(target_id: int, body: TargetBody, user: str = Depends(require_login)):
    updated = crud.update_target(target_id, body.model_dump())
    if not updated:
        raise HTTPException(404, "target not found")
    return updated


@app.delete("/api/targets/{target_id}")
def remove_target(target_id: int, user: str = Depends(require_login)):
    crud.delete_target(target_id)
    return {"ok": True}


@app.post("/api/targets/{target_id}/test")
def test_target(target_id: int, user: str = Depends(require_login)):
    row = crud.get_target(target_id, mask=False)
    if not row:
        raise HTTPException(404, "target not found")
    try:
        target = targets_mod.make_target(row["type"], row["config"])
        ok, msg = target.check()
    except Exception as exc:  # noqa: BLE001
        ok, msg = False, str(exc)
    return {"ok": ok, "message": msg}


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@app.get("/api/settings")
def get_settings(user: str = Depends(require_login)):
    return appsettings.all_settings()


@app.put("/api/settings")
def put_settings(body: dict, user: str = Depends(require_login)):
    return appsettings.update(body)


@app.post("/api/settings/test-notify")
def test_notify(user: str = Depends(require_login)):
    sent = notify.send("bt2cd2 测试通知", "如果你收到这条消息，说明通知配置成功 🎉")
    if not sent:
        return {"ok": False, "message": "未启用通知或没有配置任何渠道"}
    return {"ok": True, "message": "已发送到: " + ", ".join(sent)}


# --------------------------------------------------------------------------- #
# Metadata scraping
# --------------------------------------------------------------------------- #
class MetaSearchBody(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)


@app.post("/api/meta/search")
def meta_search(body: MetaSearchBody, user: str = Depends(require_login)):
    try:
        return meta_mod.search(body.keyword.strip())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"刮削失败: {exc}")


# Poster image proxy — avoids hotlink/geo issues and keeps the browser on our origin.
_IMG_HOSTS = ("bgm.tv", "tmdb.org", "themoviedb.org")


@app.get("/api/img")
def img_proxy(url: str, user: str = Depends(require_login)):
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not (url.startswith("https://") and any(host == h or host.endswith("." + h) for h in _IMG_HOSTS)):
        raise HTTPException(400, "url not allowed")
    proxy = settings.http_proxy or None
    try:
        with httpx.Client(timeout=20, proxy=proxy, follow_redirects=True) as c:
            r = c.get(url, headers={"User-Agent": meta_mod.UA, "Referer": "https://bgm.tv/"})
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"image fetch failed: {exc}")
    return Response(
        content=r.content,
        media_type=r.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
@app.get("/login")
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/")
def index(request: Request):
    if not security.validate_session(request.cookies.get(security.COOKIE_NAME)):
        return RedirectResponse("/login")
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(401)
async def unauthorized(request: Request, exc: HTTPException):
    # API callers get JSON; browsers hitting a page get redirected to login.
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "not authenticated"}, status_code=401)
    return RedirectResponse("/login")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
