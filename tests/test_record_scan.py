"""Verify atomic scan recording against migrated PostgreSQL app_test."""

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models import AISystem, AuditEvent, Component, Evidence, User
from app.schemas import ScanReport
from app.services.scans import (ScanActorError, ScanConflictError,
                                ScanOwnerError, record_scan)
from tests.database_fixture import isolated_database


class RecordScanTests(unittest.TestCase):
    def setUp(self):
        self.engine = self.enterContext(isolated_database())
        with Session(self.engine) as session:
            user = User(first_name="Test", last_name="Actor", email="actor@example.com", password_hash="test")
            session.add(user)
            session.commit()
            self.actor = user.id
        self.data = {
            "system": {"name": "bot", "repository_url": "https://example.com/bot", "environment": "prod"},
            "commit_sha": "a" * 40,
            "components": [{"kind": "vendor", "name": "example", "evidence": [
                {"file_path": "app/llm.py", "line_start": 1, "line_end": 2, "detector": "scan"}
            ]}],
        }

    def record(self, data=None, actor=None):
        with Session(self.engine) as session:
            return record_scan(session, ScanReport.model_validate(data or self.data),
                               self.actor if actor is None else actor)

    def counts(self):
        with Session(self.engine) as session:
            return [session.scalar(select(func.count()).select_from(model))
                    for model in [AISystem, Component, Evidence, AuditEvent]]

    def test_valid_scan_and_audit_are_saved_together(self):
        result = self.record()
        self.assertTrue(result.created)
        self.assertEqual(self.counts(), [1, 1, 1, 1])
        with Session(self.engine) as session:
            evidence = session.scalar(select(Evidence))
            self.assertEqual(evidence.commit_sha, self.data["commit_sha"])
            audit = session.scalar(select(AuditEvent))
            self.assertEqual(audit.actor_user_id, self.actor)
            self.assertEqual(audit.entity_id, result.system["id"])
            self.assertEqual(audit.action, "import")

    def test_three_identical_submissions_save_one_scan(self):
        first, second, third = self.record(), self.record(), self.record()
        self.assertEqual(first.system["id"], second.system["id"])
        self.assertEqual(second.system["id"], third.system["id"])
        self.assertFalse(second.created)
        self.assertFalse(third.created)
        self.assertEqual(self.counts(), [1, 1, 1, 1])

    def test_concurrent_identical_submissions_save_one_scan(self):
        start = Barrier(2)

        def submit():
            start.wait(timeout=5)
            return self.record()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sum(result.created for result in results), 1)
        self.assertEqual(results[0].system["id"], results[1].system["id"])
        self.assertEqual(self.counts(), [1, 1, 1, 1])

    def test_changed_content_conflicts_without_writes(self):
        self.record()
        changed = copy.deepcopy(self.data)
        changed["commit_sha"] = "b" * 40
        with self.assertRaises(ScanConflictError):
            self.record(changed)
        self.assertEqual(self.counts(), [1, 1, 1, 1])

    def test_failure_mid_scan_rolls_back_everything(self):
        # Failure at the evidence insert happens after system/component flushes.
        def fail(*args):
            raise RuntimeError("Simulated evidence failure")
        event.listen(Evidence, "before_insert", fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "Simulated evidence failure"):
                self.record()
        finally:
            event.remove(Evidence, "before_insert", fail)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_audit_failure_also_rolls_back_scan(self):
        def fail(*args):
            raise RuntimeError("Simulated audit failure")
        event.listen(AuditEvent, "before_insert", fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "Simulated audit failure"):
                self.record()
        finally:
            event.remove(AuditEvent, "before_insert", fail)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_missing_actor_and_owner_leave_no_rows(self):
        with self.assertRaises(ScanActorError):
            self.record(actor=999999)
        changed = copy.deepcopy(self.data)
        changed["system"]["owner_user_id"] = 999999
        with self.assertRaises(ScanOwnerError):
            self.record(changed)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_empty_scan_is_recorded(self):
        self.record({**self.data, "components": []})
        self.assertEqual(self.counts(), [1, 0, 0, 1])

    def test_mutated_report_without_evidence_is_rejected(self):
        report = ScanReport.model_validate(self.data)
        report.components[0].evidence.clear()
        with Session(self.engine) as session, self.assertRaises(ValidationError):
            record_scan(session, report, self.actor)
        self.assertEqual(self.counts(), [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
