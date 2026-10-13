"""Prepare the dedicated PostgreSQL test database using Alembic migrations."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import get_settings


def validate_test_database_url(value: str | None) -> URL:
    """Reject unsafe targets before connecting or applying migrations."""
    if not value:
        raise ValueError("TEST_DATABASE_URL is required for PostgreSQL tests.")
    try:
        url = make_url(value)
    except ArgumentError:
        raise ValueError("TEST_DATABASE_URL is not a valid database URL.") from None

    if url.drivername != "postgresql+psycopg" or url.database != "app_test":
        raise ValueError(
            "TEST_DATABASE_URL must use postgresql+psycopg and target app_test."
        )
    # Connection options must not redirect the target database or server.
    if url.query:
        raise ValueError("TEST_DATABASE_URL must not contain query parameters.")
    return url


def prepare_test_database() -> URL:
    settings = get_settings()
    value = (
        settings.test_database_url.get_secret_value()
        if settings.test_database_url is not None else None
    )
    url = validate_test_database_url(value)

    # Alembic reads DATABASE_URL in a fresh process. Override it only for that
    # process; the running application and its settings remain unchanged.
    environment = {
        **os.environ,
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "JWT_SECRET_KEY": "test-only-migration-key-0123456789abcdef",
        "JWT_ALGORITHM": "HS256",
    }
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        # Do not print credentials or connection strings from subprocess errors.
        raise RuntimeError(
            "Test migrations failed. Check that app_test exists and that "
            "TEST_DATABASE_URL credentials are correct."
        )
    return url


if __name__ == "__main__":
    prepare_test_database()
    print("app_test migrations applied successfully.")
