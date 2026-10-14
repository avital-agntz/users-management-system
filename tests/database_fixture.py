"""Provide migrated PostgreSQL fixtures isolated from the application database."""

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text

from tests.setup_database import prepare_test_database


@lru_cache(maxsize=1)
def get_test_engine():
    # Apply migrations once per test process; never create tables from models.
    url = prepare_test_database()
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


@contextmanager
def isolated_database():
    engine = get_test_engine()
    with engine.connect() as guard:
        if guard.execute(text("SELECT current_database()")).scalar() != "app_test":
            raise RuntimeError("Refusing test cleanup outside app_test.")
        # Serialize fixtures that share app_test, including separate test processes.
        guard.execute(text("SELECT pg_advisory_lock(714021)"))
        guard.commit()
        try:
            with engine.begin() as connection:
                connection.execute(text("TRUNCATE TABLE finding_evidence, evidence, findings, components, audit_events, ai_systems, users RESTART IDENTITY"))
            yield engine
        finally:
            try:
                with engine.begin() as connection:
                    connection.execute(text("TRUNCATE TABLE finding_evidence, evidence, findings, components, audit_events, ai_systems, users RESTART IDENTITY"))
            finally:
                guard.execute(text("SELECT pg_advisory_unlock(714021)"))
                guard.commit()
