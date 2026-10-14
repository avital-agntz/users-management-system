"""Exercise migration 2 constraints directly in PostgreSQL, without Pydantic."""

import unittest

from sqlalchemy import insert, select, inspect
from sqlalchemy.exc import IntegrityError

from app.models import AISystem, AuditEvent, Component, Evidence, Finding, FindingEvidence, User
from tests.database_fixture import isolated_database


class RegistryModelTests(unittest.TestCase):
    def setUp(self):
        # Migrations create the schema; guarded cleanup touches only app_test.
        self.engine = self.enterContext(isolated_database())
        self.user_id = self.add(User, first_name="Test", last_name="Owner",
                                email="owner@example.com", password_hash="test-only")
        self.system_id = self.add(AISystem, **self.system_values())
        self.component_id = self.add(Component, system_id=self.system_id,
                                     kind="model", name="example-model")
        self.evidence_id = self.add(Evidence, **self.evidence_values())
        self.finding_id = self.add(Finding, **self.finding_values())
        self.add(FindingEvidence, finding_id=self.finding_id, evidence_id=self.evidence_id)

    def add(self, model, **values):
        with self.engine.begin() as connection:
            statement = insert(model.__table__).values(**values)
            if "id" in model.__table__.columns:
                return connection.execute(statement.returning(model.id)).scalar_one()
            connection.execute(statement)

    def system_values(self, **changes):
        return {"name": "support-bot", "repository_url": "https://example.com/repo",
                "environment": "prod", "owner_user_id": self.user_id,
                "manifest_sha256": "a" * 64, **changes}

    def evidence_values(self, **changes):
        return {"component_id": self.component_id, "commit_sha": "a" * 40,
                "file_path": "app/llm.py", "line_start": 3, "line_end": 3,
                "detector": "import-scan", **changes}

    def finding_values(self, **changes):
        return {"system_id": self.system_id, "rule_id": "AGZ-DEMO-001",
                "severity": "high", "message": "Review observed data flow",
                "fingerprint": "example-fingerprint", **changes}

    def assert_rejected(self, model, values, sqlstate, constraint=None):
        # Each failed insert gets its own transaction, automatically rolled back.
        with self.assertRaises(IntegrityError) as caught:
            self.add(model, **values)
        self.assertEqual(caught.exception.orig.sqlstate, sqlstate)
        if constraint:
            self.assertEqual(caught.exception.orig.diag.constraint_name, constraint)

    def test_valid_registry_and_database_defaults(self):
        with self.engine.connect() as connection:
            system = connection.execute(select(AISystem.__table__)).one()
            self.assertIsNotNone(system.created_at.tzinfo)
            component = connection.execute(select(Component.__table__)).one()
            self.assertEqual(component.attributes, {})
            self.assertIsNone(component.version)
            finding = connection.execute(select(Finding.__table__)).one()
            self.assertEqual(finding.status, "open")
            self.assertIsNotNone(finding.created_at.tzinfo)

    def test_environment_check(self):
        self.assert_rejected(AISystem,
            self.system_values(name="other", manifest_sha256="b" * 64, environment="invalid"),
            "23514", "ck_ai_systems_environment")

    def test_repository_and_name_unique_together(self):
        self.assert_rejected(AISystem, self.system_values(manifest_sha256="b" * 64),
                             "23505", "uq_ai_systems_repository_name")
        # A different name in the same repository, or another repository, is valid.
        self.add(AISystem, **self.system_values(name="fraud-detector", manifest_sha256="b" * 64))
        self.add(AISystem, **self.system_values(repository_url="https://example.com/other", manifest_sha256="c" * 64))

    def test_manifest_hash_unique_and_valid(self):
        self.assert_rejected(AISystem, self.system_values(name="other"), "23505")
        for value in ["abc", "Z" * 64]:
            with self.subTest(value=value):
                self.assert_rejected(AISystem, self.system_values(name="other", manifest_sha256=value),
                                     "23514", "ck_ai_systems_manifest_sha256")

    def test_owner_foreign_key_and_nullable_owner(self):
        self.assert_rejected(AISystem,
            self.system_values(name="other", manifest_sha256="b" * 64, owner_user_id=999999), "23503")
        self.add(AISystem, **self.system_values(name="unowned", manifest_sha256="b" * 64, owner_user_id=None))

    def test_component_kind_and_attributes_checks(self):
        values = {"system_id": self.system_id, "kind": "unknown", "name": "tool"}
        self.assert_rejected(Component, values, "23514", "ck_components_kind")
        self.assert_rejected(Component, {**values, "kind": "tool", "attributes": []},
                             "23514", "ck_components_attributes_object")
        for kind in ["model", "framework", "tool", "mcp_server", "vendor", "data_source"]:
            with self.subTest(kind=kind):
                self.add(Component, system_id=self.system_id, kind=kind, name=kind)

    def test_component_system_foreign_key(self):
        self.assert_rejected(Component, {"system_id": 999999, "kind": "model", "name": "missing"}, "23503")

    def test_component_identity_is_unique_within_system(self):
        values = {"system_id": self.system_id, "kind": "model", "name": "example-model"}
        self.assert_rejected(Component, values, "23505", "uq_components_system_kind_name")
        # Version does not change logical identity; evidence locations share a row.
        self.assert_rejected(Component, {**values, "version": "2"},
                             "23505", "uq_components_system_kind_name")
        self.add(Component, **{**values, "kind": "tool"})
        other = self.add(AISystem, **self.system_values(name="other", manifest_sha256="b" * 64))
        self.add(Component, **{**values, "system_id": other})

    def test_registry_lookup_indexes_exist(self):
        inspector = inspect(self.engine)
        expected = {
            "components": ("ix_components_system_id", ["system_id"]),
            "evidence": ("ix_evidence_component_id", ["component_id"]),
            "findings": ("ix_findings_system_id", ["system_id"]),
            "finding_evidence": ("ix_finding_evidence_evidence_id", ["evidence_id"]),
            "audit_events": ("ix_audit_events_entity_type_entity_id", ["entity_type", "entity_id"]),
        }
        for table, (name, columns) in expected.items():
            with self.subTest(table=table):
                indexes = {item["name"]: item["column_names"] for item in inspector.get_indexes(table)}
                self.assertEqual(indexes[name], columns)

    def test_evidence_line_checks(self):
        for changes, constraint in [
            ({"line_start": 0}, "ck_evidence_line_start"),
            ({"line_start": 5, "line_end": 4}, "ck_evidence_line_range"),
        ]:
            with self.subTest(changes=changes):
                self.assert_rejected(Evidence, self.evidence_values(**changes), "23514", constraint)

    def test_evidence_hash_checks(self):
        for changes, constraint in [
            ({"commit_sha": "a" * 39}, "ck_evidence_commit_sha"),
            ({"commit_sha": "A" * 40}, "ck_evidence_commit_sha"),
            ({"snippet_sha256": "invalid"}, "ck_evidence_snippet_sha256"),
        ]:
            with self.subTest(changes=changes):
                self.assert_rejected(Evidence, self.evidence_values(**changes), "23514", constraint)
        self.add(Evidence, **self.evidence_values(snippet_sha256="b" * 64))

    def test_evidence_path_check(self):
        for path in ["", "/app/llm.py", "../secret", "app/../secret", "C:/secret", "app\\llm.py"]:
            with self.subTest(path=path):
                self.assert_rejected(Evidence, self.evidence_values(file_path=path),
                                     "23514", "ck_evidence_relative_path")

    def test_evidence_component_foreign_key(self):
        self.assert_rejected(Evidence, self.evidence_values(component_id=999999), "23503")

    def test_finding_severity_and_status_checks(self):
        for changes, constraint in [
            ({"severity": "critical"}, "ck_findings_severity"),
            ({"status": "closed"}, "ck_findings_status"),
        ]:
            with self.subTest(changes=changes):
                self.assert_rejected(Finding, self.finding_values(fingerprint="other", **changes), "23514", constraint)

    def test_finding_uniqueness(self):
        self.assert_rejected(Finding, self.finding_values(),
                             "23505", "uq_findings_system_rule_fingerprint")
        self.add(Finding, **self.finding_values(rule_id="AGZ-DEMO-002"))
        self.add(Finding, **self.finding_values(fingerprint="different"))

    def test_finding_system_foreign_key(self):
        self.assert_rejected(Finding, self.finding_values(system_id=999999), "23503")

    def test_evidence_link_uniqueness_and_foreign_keys(self):
        self.assert_rejected(FindingEvidence,
            {"finding_id": self.finding_id, "evidence_id": self.evidence_id}, "23505")
        for values in [
            {"finding_id": 999999, "evidence_id": self.evidence_id},
            {"finding_id": self.finding_id, "evidence_id": 999999},
        ]:
            with self.subTest(values=values):
                self.assert_rejected(FindingEvidence, values, "23503")

    def test_audit_actor_and_details_constraints(self):
        values = {"actor_user_id": self.user_id, "action": "import",
                  "entity_type": "ai_system", "entity_id": self.system_id}
        self.assert_rejected(AuditEvent, {**values, "actor_user_id": 999999}, "23503")
        self.assert_rejected(AuditEvent, {**values, "details": []},
                             "23514", "ck_audit_events_details_object")
        self.add(AuditEvent, **values)
        with self.engine.connect() as connection:
            event = connection.execute(select(AuditEvent.__table__)).one()
            self.assertEqual(event.details, {})
            self.assertIsNotNone(event.created_at.tzinfo)

    def test_required_fields_reject_sql_null(self):
        self.assert_rejected(Component,
            {"system_id": self.system_id, "kind": "model", "name": None}, "23502")
        self.assert_rejected(Evidence, self.evidence_values(detector=None), "23502")


if __name__ == "__main__":
    unittest.main()
