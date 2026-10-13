"""Check settings validation without reading .env or using real secrets."""

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.core.config import Settings


class ConfigTests(unittest.TestCase):
    def setUp(self):
        # Clear inherited variables so they cannot supply a missing test setting.
        environment = patch.dict("os.environ", {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.valid = {
            "jwt_secret_key": "test-only-secret-not-for-production",
            "database_url": "sqlite:///:memory:",
        }

    def test_missing_jwt_key_names_required_field(self):
        with self.assertRaises(ValidationError) as caught:
            Settings(_env_file=None, database_url=self.valid["database_url"])
        self.assertEqual(caught.exception.errors()[0]["loc"], ("jwt_secret_key",))
        self.assertIn("Field required", str(caught.exception))

    def test_missing_database_url_names_required_field(self):
        with self.assertRaises(ValidationError) as caught:
            Settings(_env_file=None, jwt_secret_key=self.valid["jwt_secret_key"])
        self.assertEqual(caught.exception.errors()[0]["loc"], ("database_url",))
        self.assertIn("Field required", str(caught.exception))

    def test_valid_settings_load_defaults(self):
        settings = Settings(_env_file=None, **self.valid)
        self.assertEqual(settings.database_url, "sqlite:///:memory:")
        self.assertEqual(settings.jwt_expire_minutes, 15)
        self.assertEqual(settings.profile_cache_ttl_seconds, 120)
        self.assertNotIn(self.valid["jwt_secret_key"], repr(settings))

    def test_nonpositive_durations_are_rejected(self):
        for field in ["jwt_expire_minutes", "profile_cache_ttl_seconds"]:
            for value in [0, -1]:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError) as caught:
                        Settings(_env_file=None, **self.valid, **{field: value})
                    self.assertEqual(caught.exception.errors()[0]["loc"], (field,))

    def test_empty_required_values_are_rejected(self):
        for field in ["jwt_secret_key", "database_url"]:
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, **{**self.valid, field: ""})

    def test_error_text_does_not_expose_input_values(self):
        # Missing DATABASE_URL must not print the supplied secret in its error.
        with self.assertRaises(ValidationError) as caught:
            Settings(_env_file=None, jwt_secret_key=self.valid["jwt_secret_key"])
        self.assertNotIn(self.valid["jwt_secret_key"], str(caught.exception))
        self.assertNotIn("input_value", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
