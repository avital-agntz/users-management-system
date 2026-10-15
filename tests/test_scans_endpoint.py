"""Exercise authenticated scan submissions through HTTP and PostgreSQL."""

import copy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

TEST_SETTINGS = Settings(
    _env_file=None, jwt_secret_key="scan-http-test-key-0123456789abcdef0123456789",
    database_url="postgresql+psycopg://app:test@127.0.0.1:5432/app_test",
    redis_url="redis://127.0.0.1:6379/15",
)
with patch("app.core.config.get_settings", return_value=TEST_SETTINGS):
    from app import main, security

from app.models import AISystem, AuditEvent, Component, Evidence, User
from tests.database_fixture import isolated_database


class ScansEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = self.enterContext(isolated_database())
        self.enterContext(patch.object(main, "SessionLocal", sessionmaker(bind=self.engine)))
        self.enterContext(patch.object(security, "settings", TEST_SETTINGS))
        self.client = self.enterContext(TestClient(main.app))
        with Session(self.engine) as session:
            actor = User(first_name="Scan", last_name="Actor", email="scan@example.com", password_hash="fixture")
            session.add(actor)
            session.commit()
            self.actor_id = actor.id
        token = security.create_access_token(self.actor_id)
        self.headers = {"Authorization": f"Bearer {token}"}
        self.report = {
            "system": {"name": "bot", "repository_url": "https://example.com/bot", "environment": "prod"},
            "commit_sha": "a" * 40,
            "components": [{"kind": "vendor", "name": "example", "evidence": [
                {"file_path": "app/llm.py", "line_start": 1, "line_end": 2, "detector": "scan"}
            ]}],
        }

    def counts(self):
        with Session(self.engine) as session:
            return [session.scalar(select(func.count()).select_from(model))
                    for model in [AISystem, Component, Evidence, AuditEvent]]

    def test_new_scan_then_identical_repeats(self):
        first = self.client.post("/scans", headers=self.headers, json=self.report)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["name"], "bot")
        self.assertIn("created_at", first.json())
        for _ in range(2):
            repeated = self.client.post("/scans", headers=self.headers, json=self.report)
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.json(), first.json())
        self.assertEqual(self.counts(), [1, 1, 1, 1])
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(AuditEvent)).actor_user_id, self.actor_id)

    def test_different_scan_for_same_system_returns_conflict(self):
        self.client.post("/scans", headers=self.headers, json=self.report)
        self.report["commit_sha"] = "b" * 40
        response = self.client.post("/scans", headers=self.headers, json=self.report)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.counts(), [1, 1, 1, 1])

    def test_missing_or_invalid_token_prevents_database_work(self):
        with patch.object(main, "SessionLocal", side_effect=AssertionError("Unauthorized database access")):
            for headers in [{}, {"Authorization": "Bearer invalid"}]:
                response = self.client.post("/scans", headers=headers, json=self.report)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_nonexistent_actor_returns_401(self):
        token = security.create_access_token(self.actor_id + 1000)
        response = self.client.post("/scans", headers={"Authorization": f"Bearer {token}"}, json=self.report)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_nonexistent_owner_returns_422(self):
        self.report["system"]["owner_user_id"] = self.actor_id + 1000
        response = self.client.post("/scans", headers=self.headers, json=self.report)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_invalid_report_returns_422_without_writes(self):
        reports = []
        for path, value in [
            (("components", 0, "evidence"), []),
            (("components", 0, "evidence", 0, "line_end"), 0),
            (("commit_sha",), "invalid"),
            (("actor_user_id",), self.actor_id),
        ]:
            changed = copy.deepcopy(self.report)
            target = changed
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            reports.append(changed)
        for report in reports:
            with self.subTest(report=report):
                response = self.client.post("/scans", headers=self.headers, json=report)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_empty_scan_is_accepted(self):
        self.report["components"] = []
        response = self.client.post("/scans", headers=self.headers, json=self.report)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.counts(), [1, 0, 0, 1])

    def test_mid_request_failure_rolls_back(self):
        def fail(*args):
            raise RuntimeError("Simulated audit failure")
        event.listen(AuditEvent, "before_insert", fail)
        try:
            with TestClient(main.app, raise_server_exceptions=False) as client:
                response = client.post("/scans", headers=self.headers, json=self.report)
            self.assertEqual(response.status_code, 500)
        finally:
            event.remove(AuditEvent, "before_insert", fail)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_openapi_declares_only_scans_route_and_bearer_auth(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/scans", paths)
        self.assertNotIn("/imports", paths)
        self.assertTrue(paths["/scans"]["post"]["security"])


if __name__ == "__main__":
    unittest.main()
