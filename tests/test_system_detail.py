"""Test nested system reads through HTTP against PostgreSQL app_test."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

TEST_SETTINGS = Settings(
    _env_file=None, jwt_secret_key="system-detail-key-0123456789abcdef0123456789",
    database_url="postgresql+psycopg://app:test@127.0.0.1:5432/app_test",
    redis_url="redis://127.0.0.1:6379/15",
)
with patch("app.core.config.get_settings", return_value=TEST_SETTINGS):
    from app import main, security

from app.models import User
from tests.database_fixture import isolated_database


class SystemDetailTests(unittest.TestCase):
    def setUp(self):
        self.engine = self.enterContext(isolated_database())
        self.sessions = sessionmaker(bind=self.engine)
        self.enterContext(patch.object(main, "SessionLocal", self.sessions))
        self.enterContext(patch.object(security, "settings", TEST_SETTINGS))
        self.client = self.enterContext(TestClient(main.app))
        with self.sessions() as session:
            owner = User(first_name="Owner", last_name="Test", email="owner@example.com", password_hash="fixture")
            viewer = User(first_name="Viewer", last_name="Test", email="viewer@example.com", password_hash="fixture")
            session.add_all([owner, viewer])
            session.commit()
            self.owner_id, self.viewer_id = owner.id, viewer.id
        self.headers = {"Authorization": f"Bearer {security.create_access_token(self.viewer_id)}"}
        self.owner_headers = {"Authorization": f"Bearer {security.create_access_token(self.owner_id)}"}
        self.sample_dir = Path(__file__).resolve().parents[1] / "data" / "scans"

    def submit(self, filename):
        report = json.loads((self.sample_dir / filename).read_text())
        report["system"]["owner_user_id"] = self.owner_id
        response = self.client.post("/scans", headers=self.owner_headers, json=report)
        self.assertEqual(response.status_code, 201)
        return response.json()["id"], report

    def test_detail_matches_saved_components_and_all_evidence(self):
        system_id, report = self.submit("support-bot.json")
        response = self.client.get(f"/systems/{system_id}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["owner_user_id"], self.owner_id)
        self.assertEqual(body["name"], report["system"]["name"])
        self.assertNotIn("manifest_sha256", body)
        self.assertEqual(len(body["components"]), 4)
        self.assertEqual(sum(len(c["evidence"]) for c in body["components"]), 5)
        for saved, original in zip(body["components"], report["components"]):
            self.assertEqual(saved["name"], original["name"])
            self.assertEqual(saved["version"], original.get("version"))
            self.assertEqual(saved["attributes"], original.get("attributes", {}))
            self.assertGreater(saved["id"], 0)
            for location, source in zip(saved["evidence"], original["evidence"]):
                self.assertEqual(location["commit_sha"], report["commit_sha"])
                self.assertGreater(location["id"], 0)
                self.assertIsNone(location["snippet_sha256"])
                for field, value in source.items():
                    self.assertEqual(location[field], value)

    def test_other_system_evidence_is_not_included(self):
        first_id, _ = self.submit("support-bot.json")
        other_id, _ = self.submit("refund-agent.json")
        first = self.client.get(f"/systems/{first_id}", headers=self.headers).json()
        other = self.client.get(f"/systems/{other_id}", headers=self.headers).json()
        self.assertEqual(len(first["components"]), 4)
        self.assertEqual(len(other["components"]), 2)
        first_evidence = {e["id"] for c in first["components"] for e in c["evidence"]}
        other_evidence = {e["id"] for c in other["components"] for e in c["evidence"]}
        self.assertTrue(first_evidence.isdisjoint(other_evidence))

    def test_system_without_components(self):
        report = {"system": {"name": "empty", "repository_url": "https://example.com/empty", "environment": "dev"}, "commit_sha": "a" * 40, "components": []}
        created = self.client.post("/scans", headers=self.owner_headers, json=report)
        self.assertEqual(created.status_code, 201)
        response = self.client.get(f"/systems/{created.json()['id']}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["components"], [])

    def test_missing_system_returns_404(self):
        response = self.client.get("/systems/999999", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "System not found."})

    def test_invalid_ids_return_422(self):
        for value in ["0", "-1", "abc"]:
            with self.subTest(value=value):
                self.assertEqual(self.client.get(f"/systems/{value}", headers=self.headers).status_code, 422)

    def test_authentication_precedes_database_reads(self):
        expired = jwt.encode(
            {"sub": str(self.viewer_id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            TEST_SETTINGS.jwt_secret_key.get_secret_value(), algorithm="HS256",
        )
        with patch.object(main, "SessionLocal", side_effect=AssertionError("Unauthorized read")):
            for headers in [{}, {"Authorization": "Bearer invalid"}, {"Authorization": f"Bearer {expired}"}]:
                self.assertEqual(self.client.get("/systems/1", headers=headers).status_code, 401)

    def test_read_uses_three_queries_and_performs_no_writes(self):
        system_id, _ = self.submit("support-bot.json")
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get(f"/systems/{system_id}", headers=self.headers)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(statements), 3)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in statements))


if __name__ == "__main__":
    unittest.main()
