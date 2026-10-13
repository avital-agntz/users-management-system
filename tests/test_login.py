"""
Check login logic without accessing users.db or the real signing key.
"""

import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import the application with explicit test configuration, without reading .env.
from app.core.config import Settings

IMPORT_SETTINGS = Settings(
    _env_file=None,
    jwt_secret_key="test-only-key-0123456789abcdef0123456789abcdef",
    database_url="sqlite:///:memory:",
    redis_url="redis://127.0.0.1:6379/15",
    jwt_algorithm="HS256",
    jwt_expire_minutes=15,
    profile_cache_ttl_seconds=60,
)
with patch("app.core.config.get_settings", return_value=IMPORT_SETTINGS):
    from app import main, security

from app.models import Base, User
from app.schemas import LoginRequest


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)

        session_patch = patch.object(main, "SessionLocal", self.sessions)
        session_patch.start()
        self.addCleanup(session_patch.stop)

        self.test_key = "test-only-key-0123456789abcdef0123456789abcdef"
        # Replace the settings object instead of removed JWT constants.
        test_settings = IMPORT_SETTINGS.model_copy()
        config_patch = patch.object(security, "settings", test_settings)
        config_patch.start()
        self.addCleanup(config_patch.stop)

        self.password = "learning123"
        with self.sessions() as session:
            user = User(
                first_name="Avital",
                last_name="Example",
                email="avital@example.com",
                password_hash=security.hash_password(self.password),
            )
            session.add(user)
            session.commit()
            self.user_id = user.id

    def test_valid_credentials_return_signed_token(self):
        response = main.login(
            LoginRequest(email="avital@example.com", password=self.password)
        )
        self.assertEqual(response["token_type"], "bearer")
        claims = jwt.decode(
            response["access_token"], self.test_key, algorithms=["HS256"]
        )
        self.assertEqual(claims["sub"], str(self.user_id))
        self.assertNotIn("password", claims)
        self.assertNotIn("password_hash", claims)

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            main.login(
                LoginRequest(email="avital@example.com", password="incorrect123")
            )
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Invalid email or password")

    def test_unknown_email_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            main.login(
                LoginRequest(email="unknown@example.com", password=self.password)
            )
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Invalid email or password")

    def test_token_signed_with_another_key_is_rejected(self):
        response = main.login(
            LoginRequest(email="avital@example.com", password=self.password)
        )
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(
                response["access_token"],
                "another-test-key-0123456789abcdef0123456789",
                algorithms=["HS256"],
            )


if __name__ == "__main__":
    unittest.main()
