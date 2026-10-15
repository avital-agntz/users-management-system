"""Check authenticated system discovery, filtering, and pagination."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

TEST_SETTINGS = Settings(
    _env_file=None, jwt_secret_key="systems-test-key-0123456789abcdef0123456789",
    database_url="postgresql+psycopg://app:test@127.0.0.1:5432/app_test",
    redis_url="redis://127.0.0.1:6379/15",
)
with patch("app.core.config.get_settings", return_value=TEST_SETTINGS):
    from app import main, security

from app.models import AISystem, User
from tests.database_fixture import isolated_database


class SystemsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = self.enterContext(isolated_database())
        self.enterContext(patch.object(main, "SessionLocal", sessionmaker(bind=self.engine)))
        self.enterContext(patch.object(security, "settings", TEST_SETTINGS))
        self.client = self.enterContext(TestClient(main.app))
        with Session(self.engine) as session:
            viewer = User(first_name="Viewer", last_name="Test", email="viewer@example.com", password_hash="fixture")
            owner = User(first_name="Owner", last_name="Test", email="owner@example.com", password_hash="fixture")
            session.add_all([viewer, owner])
            session.commit()
            self.viewer_id, self.owner_id = viewer.id, owner.id
        self.headers = {"Authorization": f"Bearer {security.create_access_token(self.viewer_id)}"}

    def seed_systems(self):
        # Include another user's system, an unowned one, and the viewer's system.
        with Session(self.engine) as session:
            for index, (environment, owner) in enumerate([
                ("prod", self.owner_id), ("dev", None), ("prod", self.viewer_id),
            ]):
                session.add(AISystem(
                    name=f"system-{index}", repository_url=f"https://example.com/repo-{index}",
                    environment=environment, owner_user_id=owner,
                    manifest_sha256=f"{index:064x}",
                ))
            session.commit()

    def test_empty_registry_returns_empty_page(self):
        response = self.client.get("/systems", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "total": 0, "limit": 20, "offset": 0})

    def test_all_systems_visible_regardless_of_owner(self):
        self.seed_systems()
        response = self.client.get("/systems", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        page = response.json()
        self.assertEqual(page["total"], 3)
        self.assertEqual([item["name"] for item in page["items"]], ["system-0", "system-1", "system-2"])
        self.assertEqual([item["owner_user_id"] for item in page["items"]], [self.owner_id, None, self.viewer_id])
        self.assertEqual(set(page["items"][0]), {"id", "name", "repository_url", "environment", "owner_user_id", "created_at"})

    def test_pagination_preserves_total_and_id_order(self):
        self.seed_systems()
        first = self.client.get("/systems?limit=1&offset=0", headers=self.headers).json()
        second = self.client.get("/systems?limit=1&offset=1", headers=self.headers).json()
        self.assertEqual(first["total"], 3)
        self.assertEqual(second["total"], 3)
        self.assertEqual(second["limit"], 1)
        self.assertEqual(second["offset"], 1)
        self.assertLess(first["items"][0]["id"], second["items"][0]["id"])
        self.assertEqual(second["items"][0]["name"], "system-1")

    def test_filter_applies_to_count_and_page(self):
        self.seed_systems()
        response = self.client.get("/systems?environment=prod&limit=1&offset=1", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["items"][0]["name"], "system-2")

    def test_no_matches_and_offset_past_end(self):
        self.seed_systems()
        for query, total in [("environment=staging", 0), ("offset=100", 3)]:
            with self.subTest(query=query):
                response = self.client.get(f"/systems?{query}", headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["items"], [])
                self.assertEqual(response.json()["total"], total)

    def test_invalid_query_parameters_return_422(self):
        for query in ["environment=test", "limit=0", "limit=101", "limit=abc", "offset=-1", "offset=abc"]:
            with self.subTest(query=query):
                response = self.client.get(f"/systems?{query}", headers=self.headers)
                self.assertEqual(response.status_code, 422)

    def test_authentication_rejected_before_querying(self):
        with patch.object(main, "SessionLocal", side_effect=AssertionError("Unauthorized database access")):
            for headers in [{}, {"Authorization": "Bearer invalid"}]:
                response = self.client.get("/systems", headers=headers)
                self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
