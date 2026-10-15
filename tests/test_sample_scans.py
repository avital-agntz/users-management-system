"""Check invented sample scans and their authenticated submission behavior."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.schemas import ScanReport

TEST_SETTINGS = Settings(
    _env_file=None,
    jwt_secret_key="sample-scan-test-key-0123456789abcdef0123456789",
    database_url="postgresql+psycopg://app:test@127.0.0.1:5432/app_test",
    redis_url="redis://127.0.0.1:6379/15",
)
with patch("app.core.config.get_settings", return_value=TEST_SETTINGS):
    from app import main, security

from app.models import AISystem, AuditEvent, Component, Evidence, User
from tests.database_fixture import isolated_database

SCANS_DIR = Path(__file__).resolve().parents[1] / "data" / "scans"


def load_scan(filename):
    return json.loads((SCANS_DIR / filename).read_text(encoding="utf-8"))


class SampleScanValidationTests(unittest.TestCase):
    def test_all_three_samples_match_scan_report(self):
        # Schema validation is independent of PostgreSQL and Redis.
        for filename, name in [
            ("support-bot.json", "support-bot"),
            ("refund-agent.json", "refund-agent"),
            ("faq-bot.json", "faq-bot"),
        ]:
            with self.subTest(filename=filename):
                report = ScanReport.model_validate(load_scan(filename))
                self.assertEqual(report.system.name, name)


class SampleScanSubmissionTests(unittest.TestCase):
    def setUp(self):
        # Use the migrated test database, never the application's database.
        self.engine = self.enterContext(isolated_database())
        self.enterContext(patch.object(main, "SessionLocal", sessionmaker(bind=self.engine)))
        self.enterContext(patch.object(security, "settings", TEST_SETTINGS))
        self.client = self.enterContext(TestClient(main.app))

        with Session(self.engine) as session:
            actor = User(
                first_name="Sample", last_name="Tester",
                email="samples@example.com", password_hash="test-only-fixture",
            )
            session.add(actor)
            session.commit()
            self.actor_id = actor.id

        token = security.create_access_token(self.actor_id)
        self.headers = {"Authorization": f"Bearer {token}"}
        self.report = load_scan("support-bot.json")

    def counts(self):
        # Read persisted counts in a fresh session after the HTTP transaction.
        with Session(self.engine) as session:
            return [
                session.scalar(select(func.count()).select_from(model))
                for model in [AISystem, Component, Evidence, AuditEvent]
            ]

    def test_support_bot_creates_expected_rows(self):
        response = self.client.post("/scans", headers=self.headers, json=self.report)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "support-bot")
        self.assertEqual(self.counts(), [1, 4, 5, 1])
        with Session(self.engine) as session:
            audit = session.scalar(select(AuditEvent))
            self.assertEqual(audit.actor_user_id, self.actor_id)
            self.assertEqual(audit.entity_id, response.json()["id"])

    def test_repeating_support_bot_does_not_create_rows(self):
        first = self.client.post("/scans", headers=self.headers, json=self.report)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.counts(), [1, 4, 5, 1])

        repeated = self.client.post("/scans", headers=self.headers, json=self.report)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json(), first.json())
        self.assertEqual(self.counts(), [1, 4, 5, 1])


if __name__ == "__main__":
    unittest.main()
