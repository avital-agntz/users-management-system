"""Check token expiration without waiting or accessing the real database."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Match the application's current direct-file imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

TEST_KEY = "expiration-test-key-0123456789abcdef0123456789"
with patch.dict("os.environ", {
    "JWT_SECRET_KEY": TEST_KEY,
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRE_MINUTES": "15",
}):
    import main
    import security

from models import Base, User


class TokenExpirationTests(unittest.TestCase):
    def setUp(self):
        # Each test gets predictable configuration, restored afterward.
        for name, value in [
            ("JWT_SECRET_KEY", TEST_KEY),
            ("JWT_ALGORITHM", "HS256"),
            ("JWT_EXPIRE_MINUTES", 15),
        ]:
            replacement = patch.object(security, name, value)
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
        # Share one temporary connection with TestClient's request threads.
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
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
