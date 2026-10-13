"""
Define and validate shared application configuration.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # Configuration for Pydantic settings by env file
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    jwt_secret_key: SecretStr = Field(min_length=1)
    database_url: str = Field(min_length=1)
    test_database_url: SecretStr | None = None

    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_expire_minutes: int = Field(default=15, gt=0)
    redis_url: str = "redis://127.0.0.1:6379/0"
    profile_cache_ttl_seconds: int = Field(default=120, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached instance of the Settings class.
    This function uses the lru_cache decorator to cache the Settings instance,
    ensuring that the configuration is loaded only once and reused across the application."""
    return Settings()
