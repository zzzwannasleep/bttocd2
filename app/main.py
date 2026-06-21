"""FastAPI application: login-protected web UI + JSON API."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import clouddrive_client, crud, scheduler, security
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
    target_folder: str = Field(default="/", max_length=500)
    enabled: bool = True

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
    connected, msg = clouddrive_client.check_connection()
    return {
        "cd2": {"url": settings.cd2_url, "connected": connected, "message": msg},
        "counts": crud.counts(),
        "anti_block": {
            "host_min_interval": settings.host_min_interval,
            "fetch_jitter_seconds": settings.fetch_jitter_seconds,
            "flaresolverr": bool(settings.flaresolverr_url),
            "proxy": bool(settings.http_proxy),
        },
    }


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
