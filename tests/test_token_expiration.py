"""Check token expiration without waiting or accessing the real database."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

TEST_KEY = "expiration-test-key-0123456789abcdef0123456789"
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
    from app import main, security

from app.models import User
from tests.database_fixture import isolated_database


class TokenExpirationTests(unittest.TestCase):
    def setUp(self):
        # Each test gets predictable configuration, restored afterward.
        replacement = patch.object(security, "settings", IMPORT_SETTINGS.model_copy())
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_new_token_expires_in_fifteen_minutes(self):
        before = datetime.now(timezone.utc).timestamp()
        token = security.create_access_token(1)
        after = datetime.now(timezone.utc).timestamp()
        payload = jwt.decode(token, TEST_KEY, algorithms=["HS256"])

        # JWT timestamps have whole-second precision, so allow rounding down.
        self.assertGreaterEqual(payload["exp"], before + 15 * 60 - 1)
        self.assertLessEqual(payload["exp"], after + 15 * 60)
        self.assertEqual(security.verify_access_token(token), 1)

    def test_expired_token_is_rejected(self):
        # A past expiration tests rejection immediately, without sleeping.
        token = jwt.encode(
            {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            TEST_KEY,
            algorithm="HS256",
        )
        with self.assertRaises(jwt.ExpiredSignatureError):
            security.verify_access_token(token)

    def test_missing_expiration_is_rejected(self):
        token = jwt.encode({"sub": "1"}, TEST_KEY, algorithm="HS256")
        with self.assertRaises(jwt.MissingRequiredClaimError) as caught:
            security.verify_access_token(token)
        self.assertEqual(caught.exception.claim, "exp")

    def test_expired_token_cannot_update_user(self):
        # Use PostgreSQL for the HTTP check, with guarded test cleanup.
        engine = self.enterContext(isolated_database())
        sessions = sessionmaker(bind=engine)
        replacement = patch.object(main, "SessionLocal", sessions)
        replacement.start()
        self.addCleanup(replacement.stop)

        with sessions() as session:
            user = User(
                first_name="Original", last_name="Example",
                email="expiration@example.com", password_hash="test-placeholder",
            )
            session.add(user)
            session.commit()
            user_id = user.id

        expired_token = jwt.encode(
            {"sub": str(user_id),
             "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            TEST_KEY,
            algorithm="HS256",
        )
        with TestClient(main.app) as client:
            response = client.put(
                "/update",
                headers={"Authorization": f"Bearer {expired_token}"},
                json={"first_name": "Should not be saved"},
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

        # Check stored data through a fresh session after the rejected request.
        with sessions() as session:
            self.assertEqual(session.get(User, user_id).first_name, "Original")


if __name__ == "__main__":
    unittest.main()
