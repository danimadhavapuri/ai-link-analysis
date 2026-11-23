"""Application configuration — loaded from environment variables / .env file."""
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Service ──────────────────────────────────────────────────────────────
    APP_NAME: str = "AI-Powered Website Link Analysis API"
    APP_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 4000
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # ── LLM ──────────────────────────────────────────────────────────────────
    # Primary: gemini-3.5-flash (fast, highly available, supported in Google AI Studio)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    THINKING_LEVEL: str = "medium"           # none | low | medium | high
    FALLBACK_MODEL: str = "gemini-3.8-flash"

    # ── Scraping ─────────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: float = 25.0            # total per-hop timeout (seconds)
    REQUEST_CONNECT_TIMEOUT: float = 8.0
    REQUEST_READ_TIMEOUT: float = 20.0
    MAX_REDIRECTS: int = 5
    MAX_CONTENT_CHARS: int = 15_000          # chars sent to LLM (token budget)
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # ── Cache ─────────────────────────────────────────────────────────────────
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 3600
    CACHE_MAX_ITEMS: int = 256

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
