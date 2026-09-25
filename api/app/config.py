"""Centralized configuration. All secrets come from the environment."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PyZapp API"
    environment: str = "development"  # development | production

    # Public auth: end users / SDK send this as `X-API-Key`.
    api_key: str = "dev-change-me"

    # Internal Baileys service.
    baileys_base_url: str = "http://localhost:3001"
    internal_api_key: str = ""
    baileys_timeout_s: float = 15.0

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    # SQLite file for instance metadata. Empty = in-memory (ephemeral).
    database_path: str = ""


def get_settings() -> Settings:
    return Settings()
