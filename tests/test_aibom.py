"""Verify authenticated grouped inventories against PostgreSQL app_test."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import get_args
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.schemas import ComponentKind

TEST_SETTINGS = Settings(
    _env_file=None, jwt_secret_key="aibom-test-key-0123456789abcdef0123456789",
    database_url="postgresql+psycopg://app:test@127.0.0.1:5432/app_test",
    redis_url="redis://127.0.0.1:6379/15",
)
with patch("app.core.config.get_settings", return_value=TEST_SETTINGS):
    from app import main, security

from app.models import AuditEvent, User
from tests.database_fixture import isolated_database


class AIBOMTests(unittest.TestCase):
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

    def submit(self, filename):
        path = Path(__file__).resolve().parents[1] / "data" / "scans" / filename
        report = json.loads(path.read_text())
        report["system"]["owner_user_id"] = self.owner_id
        response = self.client.post("/scans", headers=self.owner_headers, json=report)
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def test_groups_preserve_complete_components_and_evidence(self):
        system_id = self.submit("support-bot.json")
        detail = self.client.get(f"/systems/{system_id}", headers=self.headers).json()
        response = self.client.get(f"/systems/{system_id}/aibom", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["system"], {k: v for k, v in detail.items() if k != "components"})
        self.assertEqual(body["system"]["owner_user_id"], self.owner_id)
        groups = body["components_by_kind"]
        self.assertEqual(set(groups), set(get_args(ComponentKind)))
        for kind, items in groups.items():
            self.assertEqual(items, [c for c in detail["components"] if c["kind"] == kind])
        self.assertEqual(sum(len(c["evidence"]) for items in groups.values() for c in items), 5)
        self.assertEqual(groups["framework"], [])
        self.assertEqual(groups["mcp_server"], [])

    def test_systems_are_isolated(self):
        self.submit("support-bot.json")
        other_id = self.submit("refund-agent.json")
        response = self.client.get(f"/systems/{other_id}/aibom", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        groups = response.json()["components_by_kind"]
        self.assertEqual([c["name"] for c in groups["tool"]], ["issue_refund"])
        self.assertEqual([c["name"] for c in groups["framework"]], ["langchain"])
        self.assertEqual(groups["vendor"], [])

    def test_empty_scan_has_all_empty_groups(self):
        report = {"system": {"name": "empty", "repository_url": "https://example.com/empty", "environment": "dev"}, "commit_sha": "a" * 40, "components": []}
        created = self.client.post("/scans", headers=self.owner_headers, json=report)
        self.assertEqual(created.status_code, 201)
        response = self.client.get(f"/systems/{created.json()['id']}/aibom", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["components_by_kind"], {k: [] for k in get_args(ComponentKind)})

    def test_missing_system_and_invalid_ids(self):
        self.assertEqual(self.client.get("/systems/999999/aibom", headers=self.headers).status_code, 404)
        for system_id in ["0", "-1", "abc"]:
            with self.subTest(system_id=system_id):
                self.assertEqual(self.client.get(f"/systems/{system_id}/aibom", headers=self.headers).status_code, 422)

    def test_authentication_precedes_database_reads(self):
        expired = jwt.encode(
            {"sub": str(self.viewer_id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            TEST_SETTINGS.jwt_secret_key.get_secret_value(), algorithm="HS256",
        )
        with patch.object(main, "SessionLocal", side_effect=AssertionError("Unauthorized read")):
            for headers in [{}, {"Authorization": "Bearer invalid"}, {"Authorization": f"Bearer {expired}"}]:
                self.assertEqual(self.client.get("/systems/1/aibom", headers=headers).status_code, 401)

    def test_read_is_repeatable_and_uses_three_selects(self):
        system_id = self.submit("support-bot.json")
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            first = self.client.get(f"/systems/{system_id}/aibom", headers=self.headers)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(statements), 3)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in statements))
        second = self.client.get(f"/systems/{system_id}/aibom", headers=self.headers)
        self.assertEqual(first.json(), second.json())
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AuditEvent)), 1)


if __name__ == "__main__":
    unittest.main()
