from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Server Settings
    APP_NAME: str = "AI-Powered Website Link Analysis API"
    APP_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 4000
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # LLM Settings
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    FALLBACK_MODEL: str = "gemini-2.0-flash"

    # Website Extraction Settings
    REQUEST_TIMEOUT: float = 15.0
    MAX_REDIRECTS: int = 5
    MAX_CONTENT_LENGTH: int = 15000  # Token optimization: trim cleaned content
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
        "(compatible; LinkAnalysisBot/1.0)"
    )

    # In-Memory Cache Settings (Cost & latency optimization)
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 3600
    CACHE_MAX_ITEMS: int = 256

    # Allowed URL schemes
    ALLOWED_SCHEMES: List[str] = ["http", "https"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return Settings()
