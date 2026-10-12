"""
Test update requests through middleware, validation, and database storage.
"""

import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_KEY = "test-only-key-0123456789abcdef0123456789abcdef"
with patch.dict("os.environ", {"JWT_SECRET_KEY": TEST_KEY, "JWT_ALGORITHM": "HS256"}):
    from app import main
    from app import security

from app.models import Base, User


class UpdateTests(unittest.TestCase):
    def setUp(self):
        # TestClient runs requests in other threads. Share one temporary SQLite
        # connection so every session sees the same in-memory database.
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)

        # Replace application configuration only for this test; cleanup restores it.
        for target, name, value in [
            (main, "SessionLocal", self.sessions),
            (security, "JWT_SECRET_KEY", TEST_KEY),
            (security, "JWT_ALGORITHM", "HS256"),
        ]:
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

        self.client = self.enterContext(TestClient(main.app))
        self.password = "learning123"

        # Register two accounts through HTTP, then log in as the first one.
        self.first = self.register("Avital", "first@example.com")
        self.second = self.register("Other", "second@example.com")
        response = self.client.post(
            "/login", json={"email": self.first["email"], "password": self.password}
        )
        self.assertEqual(response.status_code, 200)
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.original = self.read_users()

    def register(self, name, email):
        response = self.client.post(
            "/register",
            json={
                "first_name": name,
                "last_name": "Example",
                "email": email,
                "password": self.password,
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def read_users(self):
        # A fresh session checks what was actually saved, not just the response.
        with self.sessions() as session:
            return {
                user_id: {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "password_hash": user.password_hash,
                }
                for user_id in [self.first["id"], self.second["id"]]
                if (user := session.get(User, user_id)) is not None
            }

    def test_partial_update_preserves_omitted_fields_and_other_user(self):
        response = self.client.put(
            "/update", headers=self.headers, json={"first_name": "  Updated  "}
        )
        self.assertEqual(response.status_code, 200)
        expected = {**self.first, "first_name": "Updated"}
        self.assertEqual(response.json(), expected)
        saved = self.read_users()
        self.assertEqual(
            saved[self.first["id"]],
            {
                **self.original[self.first["id"]],
                "first_name": "Updated",
            },
        )
        self.assertEqual(saved[self.second["id"]], self.original[self.second["id"]])

    def test_email_change_preserves_login_and_token_identity(self):
        response = self.client.put(
            "/update",
            headers=self.headers,
            json={"last_name": "Changed", "email": "new@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.read_users()[self.first["id"]]["email"], "new@example.com"
        )
        response = self.client.post(
            "/login", json={"email": "new@example.com", "password": self.password}
        )
        self.assertEqual(response.status_code, 200)
        # The original token identifies an ID, so changing email doesn't invalidate it.
        response = self.client.put(
            "/update", headers=self.headers, json={"first_name": "Still me"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.first["id"])

    def test_invalid_credentials_make_no_changes(self):
        wrong_signature = jwt.encode(
            {"sub": str(self.first["id"])},
            "different-test-key-0123456789abcdef",
            algorithm="HS256",
        )
        tokens = [
            None,
            "Basic abc",
            "Bearer",
            "Bearer not-a-token",
            f"Bearer {wrong_signature}",
        ]
        # These tokens are correctly signed but have invalid or missing subjects.
        for payload in [{}, {"sub": "abc"}, {"sub": "0"}, {"sub": "-1"}]:
            tokens.append(f"Bearer {jwt.encode(payload, TEST_KEY, algorithm='HS256')}")
        for header in tokens:
            with self.subTest(header=header):
                headers = {} if header is None else {"Authorization": header}
                response = self.client.put(
                    "/update", headers=headers, json={"first_name": "Rejected"}
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
                self.assertEqual(self.read_users(), self.original)

    def test_invalid_input_makes_no_changes(self):
        for body in [
            {},
            {"email": "invalid"},
            {"first_name": "   "},
            {"first_name": "x" * 51},
            {"email": None},
            {"first_name": None},
            {"last_name": None},
            {"id": self.second["id"]},
            {"password": "new-password"},
        ]:
            with self.subTest(body=body):
                response = self.client.put("/update", headers=self.headers, json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(self.read_users(), self.original)

    def test_duplicate_email_rolls_back_all_changes(self):
        response = self.client.put(
            "/update",
            headers=self.headers,
            json={"first_name": "Must roll back", "email": self.second["email"]},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.read_users(), self.original)

    def test_keeping_own_email_is_allowed(self):
        response = self.client.put(
            "/update", headers=self.headers, json={"email": self.first["email"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.read_users(), self.original)

    def test_nonexistent_user_is_rejected(self):
        token = security.create_access_token(
            max(self.first["id"], self.second["id"]) + 1
        )
        response = self.client.put(
            "/update",
            headers={"Authorization": f"Bearer {token}"},
            json={"first_name": "Rejected"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.read_users(), self.original)


if __name__ == "__main__":
    unittest.main()
