"""Check public health responses without using real PostgreSQL or Redis."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from sqlalchemy.exc import OperationalError

from app.core.config import Settings

TEST_SETTINGS = Settings(
    _env_file=None,
    jwt_secret_key="health-test-key-0123456789abcdef0123456789",
    database_url="postgresql+psycopg://app:test@127.0.0.1:5432/app_test",
    redis_url="redis://127.0.0.1:6379/15",
)
with patch("app.core.config.get_settings", return_value=TEST_SETTINGS):
    from app import cache, database, main


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.engine = MagicMock()
        connection = self.engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.scalar.return_value = 1
        self.redis = MagicMock()
        self.redis.ping.return_value = True
        for target, name, replacement in [
            (database, "engine", self.engine),
            (cache, "redis_client", self.redis),
        ]:
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = self.enterContext(TestClient(main.app))

    def test_healthy_without_authentication(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})
        self.redis.ping.assert_called_once()

    def test_database_failure_and_recovery(self):
        # Simulate an outage, then recovery without recreating the app.
        self.engine.connect.side_effect = OperationalError(
            "SELECT 1", {}, Exception("private connection details")
        )
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "unhealthy", "failed_dependencies": ["database"],
        })
        self.redis.ping.assert_called_once()
        self.engine.connect.side_effect = None
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_redis_failure(self):
        self.redis.ping.side_effect = ConnectionError("private Redis details")
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "unhealthy", "failed_dependencies": ["redis"],
        })

    def test_both_dependencies_fail_without_leaking_details(self):
        self.engine.connect.side_effect = OperationalError(
            "SELECT 1", {}, Exception("private database details")
        )
        self.redis.ping.side_effect = ConnectionError("private Redis details")
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "unhealthy", "failed_dependencies": ["database", "redis"],
        })
        self.assertNotIn("private", response.text)


if __name__ == "__main__":
    unittest.main()
