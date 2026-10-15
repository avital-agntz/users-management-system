"""Verify test-database safeguards without connecting to PostgreSQL."""

import unittest
from unittest.mock import patch

from app.core.config import Settings
from tests.setup_database import (prepare_test_database,
                                  validate_test_database_url)


class DatabaseSetupTests(unittest.TestCase):
    def test_only_explicit_test_database_is_accepted(self):
        url = validate_test_database_url(
            "postgresql+psycopg://app:test@127.0.0.1:5432/app_test"
        )
        self.assertEqual(url.database, "app_test")

    def test_unsafe_or_missing_targets_are_rejected(self):
        for value in [
            None, "", "not-a-url", "sqlite:///app_test",
            "postgresql+psycopg://app:test@localhost/app",
            "postgresql+psycopg://app:test@localhost/app_test?dbname=app",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_test_database_url(value)

    def test_migrations_use_test_url_not_application_url(self):
        settings = Settings(
            _env_file=None, jwt_secret_key="test-key",
            database_url="postgresql+psycopg://app:test@localhost/app",
            test_database_url="postgresql+psycopg://app:test@localhost/app_test",
        )
        with patch("tests.setup_database.get_settings", return_value=settings), patch(
            "tests.setup_database.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            url = prepare_test_database()
        self.assertEqual(url.database, "app_test")
        self.assertEqual(run.call_args.kwargs["env"]["DATABASE_URL"],
                         settings.test_database_url.get_secret_value())
        self.assertTrue(settings.database_url.endswith("/app"))

    def test_unsafe_target_never_runs_migrations(self):
        settings = Settings(
            _env_file=None, jwt_secret_key="test-key", database_url="postgresql+psycopg://app:test@localhost/app",
            test_database_url="postgresql+psycopg://app:test@localhost/app",
        )
        with patch("tests.setup_database.get_settings", return_value=settings), patch(
            "tests.setup_database.subprocess.run"
        ) as run:
            with self.assertRaises(ValueError):
                prepare_test_database()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
