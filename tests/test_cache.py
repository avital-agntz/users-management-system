"""
Check profile caching without accessing live Redis or users.db.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from sqlalchemy.orm import sessionmaker

TEST_KEY = "cache-test-key-0123456789abcdef0123456789abcdef"
# Import the application with explicit test configuration, without reading .env.
from app.core.config import Settings

IMPORT_SETTINGS = Settings(
    _env_file=None,
    jwt_secret_key=TEST_KEY,
    database_url="postgresql+psycopg://app:test@127.0.0.1:5432/app_test",
    redis_url="redis://127.0.0.1:6379/15",
    jwt_algorithm="HS256",
    jwt_expire_minutes=15,
    profile_cache_ttl_seconds=60,
)
with patch("app.core.config.get_settings", return_value=IMPORT_SETTINGS):
    from app import cache, main, security

from app.models import User
from tests.database_fixture import isolated_database


class FakeRedis:
    """Small Redis substitute with a controllable clock and failure switches."""

    def __init__(self):
        self.values = {}
        self.now = 0
        self.calls = []
        self.fail_get = self.fail_set = self.fail_delete = False

    def get(self, key):
        self.calls.append(("get", key))
        if self.fail_get:
            raise ConnectionError("Simulated read failure")
        value, expires_at = self.values.get(key, (None, None))
        if expires_at is not None and self.now >= expires_at:
            self.values.pop(key, None)
            return None
        return value

    def set(self, key, value, ex):
        self.calls.append(("set", key))
        if self.fail_set:
            raise ConnectionError("Simulated write failure")
        self.values[key] = (value, self.now + ex)
        return True

    def delete(self, key):
        self.calls.append(("delete", key))
        if self.fail_delete:
            raise ConnectionError("Simulated delete failure")
        return int(self.values.pop(key, None) is not None)


class CacheTests(unittest.TestCase):
    def setUp(self):
        # Use migrated app_test; HTTP requests open their own sessions.
        self.engine = self.enterContext(isolated_database())
        self.sessions = sessionmaker(bind=self.engine)
        self.redis = FakeRedis()

        # Patch the actual cache module used by the endpoints, not live Redis.
        for target, name, value in [
            (main, "SessionLocal", self.sessions),
            (cache, "redis_client", self.redis),
            (cache, "settings", IMPORT_SETTINGS.model_copy()),
            (security, "settings", IMPORT_SETTINGS.model_copy()),
        ]:
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.client = self.enterContext(TestClient(main.app))

        # These tests target caching, so fixture users need no real password hash.
        with self.sessions() as session:
            first = User(
                first_name="Avital",
                last_name="Example",
                email="first@example.com",
                password_hash="test-placeholder",
            )
            second = User(
                first_name="Other",
                last_name="Example",
                email="second@example.com",
                password_hash="test-placeholder",
            )
            session.add_all([first, second])
            session.commit()
            self.user_id, self.other_id = first.id, second.id
        self.expected = {
            "id": self.user_id,
            "first_name": "Avital",
            "last_name": "Example",
            "email": "first@example.com",
        }
        self.key = f"users-management:profile:{self.user_id}"
        token = security.create_access_token(self.user_id)
        self.headers = {"Authorization": f"Bearer {token}"}

    def get_profile(self):
        return self.client.get("/profile", headers=self.headers)

    def test_miss_reads_database_and_caches_public_profile(self):
        response = self.get_profile()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.expected)
        value, expires_at = self.redis.values[self.key]
        self.assertEqual(json.loads(value), self.expected)
        self.assertEqual(expires_at, 60)

    def test_hit_does_not_open_database_session(self):
        cache.cache_profile(self.expected)
        # Fail the test if the endpoint accesses SQLite on a valid cache hit.
        with patch.object(
            main, "SessionLocal", side_effect=AssertionError("Unexpected database read")
        ):
            response = self.get_profile()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.expected)

    def test_expiration_reads_database_again(self):
        self.get_profile()
        self.redis.now = 61  # Advance fake time instead of waiting a minute.
        with patch.object(main, "SessionLocal", wraps=self.sessions) as factory:
            response = self.get_profile()
        self.assertEqual(response.status_code, 200)
        factory.assert_called_once()
        self.assertEqual(self.redis.values[self.key][1], 121)

    def test_update_refreshes_cache_and_preserves_other_user(self):
        self.get_profile()
        response = self.client.put(
            "/update", headers=self.headers, json={"first_name": "Updated"}
        )
        self.assertEqual(response.status_code, 200)
        expected = {**self.expected, "first_name": "Updated"}
        self.assertEqual(json.loads(self.redis.get(self.key)), expected)
        self.assertEqual(self.get_profile().json(), expected)
        with self.sessions() as session:
            self.assertEqual(session.get(User, self.user_id).first_name, "Updated")
            self.assertEqual(session.get(User, self.other_id).first_name, "Other")

    def test_duplicate_email_does_not_change_cache(self):
        self.get_profile()
        response = self.client.put(
            "/update",
            headers=self.headers,
            json={"first_name": "Rejected", "email": "second@example.com"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(self.redis.get(self.key)), self.expected)
        with self.sessions() as session:
            self.assertEqual(session.get(User, self.user_id).first_name, "Avital")

    def test_invalid_cached_data_falls_back_to_database(self):
        for value in [
            "not-json",
            "[]",
            json.dumps({"id": self.user_id}),
            json.dumps({**self.expected, "id": self.other_id}),
            json.dumps({**self.expected, "password_hash": "must-not-leak"}),
        ]:
            with self.subTest(value=value):
                self.redis.set(self.key, value, ex=60)
                with self.assertLogs("app.cache", level="WARNING"):
                    response = self.get_profile()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), self.expected)

    def test_redis_read_failure_falls_back_to_database(self):
        self.redis.fail_get = True
        with self.assertLogs("app.cache", level="WARNING"):
            response = self.get_profile()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.expected)

    def test_failed_refresh_deletes_old_entry(self):
        self.get_profile()
        self.redis.fail_set = True
        with self.assertLogs("app.cache", level="WARNING"):
            response = self.client.put(
                "/update", headers=self.headers, json={"first_name": "Updated"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(("delete", self.key), self.redis.calls)
        self.assertNotIn(self.key, self.redis.values)
        self.redis.fail_set = False
        self.assertEqual(self.get_profile().json()["first_name"], "Updated")

    def test_failed_write_and_delete_do_not_undo_database_update(self):
        self.get_profile()
        self.redis.fail_set = self.redis.fail_delete = True
        with self.assertLogs("app.cache", level="WARNING"):
            response = self.client.put(
                "/update", headers=self.headers, json={"first_name": "Updated"}
            )
        self.assertEqual(response.status_code, 200)
        with self.sessions() as session:
            self.assertEqual(session.get(User, self.user_id).first_name, "Updated")
        # Both failures can leave stale data; its original TTL still limits it.
        self.assertEqual(json.loads(self.redis.values[self.key][0]), self.expected)
        self.redis.now = 61
        self.assertIsNone(self.redis.get(self.key))

    def test_authentication_is_required_even_when_profile_is_cached(self):
        self.get_profile()
        expired = jwt.encode(
            {
                "sub": str(self.user_id),
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            TEST_KEY,
            algorithm="HS256",
        )
        for headers in [
            {},
            {"Authorization": "Bearer invalid"},
            {"Authorization": f"Bearer {expired}"},
        ]:
            with self.subTest(headers=headers):
                self.redis.calls.clear()
                response = self.client.get("/profile", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(self.redis.calls, [])

    def test_users_have_separate_cache_entries(self):
        self.get_profile()
        token = security.create_access_token(self.other_id)
        response = self.client.get(
            "/profile", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.other_id)
        self.assertEqual(len(self.redis.values), 2)
        self.assertEqual(self.get_profile().json(), self.expected)


if __name__ == "__main__":
    unittest.main()
