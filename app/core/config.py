"""
Define and validate shared application configuration.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    # Where the app runs: "development" on a laptop (default), "production" on AWS.
    app_env: Literal["development", "test", "production"] = "development"

    # Runs after all fields are loaded, so it can compare app_env with database_url.
    @model_validator(mode="after")
    def require_secure_database_in_production(self):
        # In production, only an encrypted, certificate-checked PostgreSQL connection is allowed.
        if self.app_env == "production":
            # Block any other database (e.g. SQLite), so the app cannot quietly use the wrong one.
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires a PostgreSQL DATABASE_URL.")
            # verify-full = encrypt the connection AND check the server's certificate,
            # so the app knows it is talking to the real RDS, not an impostor.
            if "sslmode=verify-full" not in self.database_url:
                raise ValueError(
                    "Production requires sslmode=verify-full in DATABASE_URL."
                )
            # The error messages never include the URL itself, because it contains the password.
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached instance of the Settings class.
    This function uses the lru_cache decorator to cache the Settings instance,
    ensuring that the configuration is loaded only once and reused across the application."""
    return Settings()
