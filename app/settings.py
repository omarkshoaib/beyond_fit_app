from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from pydantic_settings import BaseSettings, SettingsConfigDict


_CONFIG_DIR = Path(__file__).parent / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────
    database_url: str = "sqlite:///./beyond_fit.db"

    # ── LLM / OpenRouter ───────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model_id: str = "google/gemini-3.1-flash-lite-preview"
    llm_temperature: float = 0.4

    # ── Telegram ────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    admin_chat_id: Optional[int] = None
    # New role gate. Bot uses this; legacy admin_chat_id is kept as fallback.
    super_admin_telegram_user_id: Optional[int] = None

    # ── Subscription / payment ─────────────────────────────────────
    subscription_price_1m_egp: int = 1500
    subscription_price_3m_egp: int = 3500
    instapay_payee_handle: str = ""
    instapay_display_name: str = ""

    # ── FAQ rate-limit ─────────────────────────────────────────────
    faq_rate_limit_per_hour: int = 5

    # ── Email ───────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # ── Auth ────────────────────────────────────────────────────────
    auth_secret_key: str = "change-me-in-production"
    # Hardcoded super-admin email. Lifespan self-heals this account so the
    # super-admin can never lose their flags. Cannot be demoted via the API.
    super_admin_email: str = "omarkshoaib@outlook.com"

    # ── CORS ────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins. Default "*" = open (dev only).
    # Production: set CORS_ALLOWED_ORIGINS=https://app.example.com,https://www.example.com
    cors_allowed_origins: str = "*"

    # ── Feature flags ───────────────────────────────────────────────
    feature_nutrition_enabled: bool = False

    # ── Cached TOML config ─────────────────────────────────────────
    @property
    def workout_constants(self) -> dict:
        return _load_toml(_CONFIG_DIR / "workout_constants.toml")


def _load_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
