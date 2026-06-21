"""Configuration loaded from environment variables (12-factor style).

All secrets come from the environment so nothing sensitive lives in the image
or the database. See `.env.example` for the full list.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


# A small, realistic desktop UA pool. Rotated per request to look less robotic.
_DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]


@dataclass
class Settings:
    # --- storage ---
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "/data")))

    # --- web UI auth ---
    web_username: str = os.getenv("WEB_USERNAME", "admin")
    web_password: str = os.getenv("WEB_PASSWORD", "")
    secret_key: str = os.getenv("SECRET_KEY", "")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))

    # --- CloudDrive2 ---
    cd2_url: str = os.getenv("CD2_URL", "http://127.0.0.1:19798")
    cd2_username: str = os.getenv("CD2_USERNAME", "")
    cd2_password: str = os.getenv("CD2_PASSWORD", "")
    default_target_folder: str = os.getenv("DEFAULT_TARGET_FOLDER", "/")

    # Fallback login cookie for 1lou-style sites that gate .torrent downloads.
    # Per-feed cookie takes precedence; this is the default when a feed has none.
    onelou_cookie: str = os.getenv("ONELOU_COOKIE", "")

    # --- anti rate-limit / anti Cloudflare ---
    # Minimum seconds between two requests to the SAME host.
    host_min_interval: int = int(os.getenv("HOST_MIN_INTERVAL", "30"))
    # Extra random delay (0..jitter) added before each fetch to avoid a fixed cadence.
    fetch_jitter_seconds: int = int(os.getenv("FETCH_JITTER_SECONDS", "20"))
    # Default feed poll interval in minutes when the user does not set one.
    default_interval_minutes: int = int(os.getenv("DEFAULT_INTERVAL_MINUTES", "30"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "45"))
    # Optional FlareSolverr endpoint (e.g. http://flaresolverr:8191) for hard CF challenges.
    flaresolverr_url: str = os.getenv("FLARESOLVERR_URL", "")
    # Optional outbound proxy for all crawling traffic.
    http_proxy: str = os.getenv("HTTP_PROXY", "") or os.getenv("CRAWL_PROXY", "")
    user_agents: list[str] = field(default_factory=lambda: _split(os.getenv("USER_AGENTS")) or _DEFAULT_USER_AGENTS)

    # Hard cap on how many new items a single feed run may push (safety valve).
    max_items_per_run: int = int(os.getenv("MAX_ITEMS_PER_RUN", "20"))

    def __post_init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Persist a generated secret/password so sessions survive restarts even
        # when the operator did not provide one.
        state_file = self.data_dir / "secret.key"
        if not self.secret_key:
            if state_file.exists():
                self.secret_key = state_file.read_text(encoding="utf-8").strip()
            else:
                self.secret_key = secrets.token_urlsafe(48)
                state_file.write_text(self.secret_key, encoding="utf-8")
                try:
                    state_file.chmod(0o600)
                except OSError:
                    pass

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bt2cd2.db"


settings = Settings()
