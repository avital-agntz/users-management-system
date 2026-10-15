"""Validate synthetic scan reports without database or network access."""

import copy
import unittest
from datetime import date

from pydantic import ValidationError

from app.schemas import ScanReport


class ScanSchemaTests(unittest.TestCase):
    def setUp(self):
        self.scan_report = {
            "system": {"name": "support-bot", "repository_url": "https://github.com/example/repo",
                       "environment": "prod"},
            "commit_sha": "a" * 40,
            "components": [{"kind": "tool", "name": "refund", "attributes": {"writes": True},
                            "evidence": [{"file_path": "app/tools.py", "line_start": 3,
                                          "line_end": 5, "detector": "tool-scan"}]}],
        }

    def test_valid_scan_report(self):
        result = ScanReport.model_validate(self.scan_report)
        self.assertEqual(result.components[0].evidence[0].line_start, 3)

    def test_empty_and_omitted_components(self):
        self.scan_report["components"] = []
        self.assertEqual(ScanReport.model_validate(self.scan_report).components, [])
        del self.scan_report["components"]
        self.assertEqual(ScanReport.model_validate(self.scan_report).components, [])

    def test_evidence_is_required_and_nonempty(self):
        for evidence in [None, []]:
            with self.subTest(evidence=evidence):
                self.scan_report["components"][0]["evidence"] = evidence
                with self.assertRaises(ValidationError):
                    ScanReport.model_validate(self.scan_report)
        del self.scan_report["components"][0]["evidence"]
        with self.assertRaises(ValidationError):
            ScanReport.model_validate(self.scan_report)

    def test_extra_fields_at_every_level(self):
        for path in [(), ("system",), ("components", 0), ("components", 0, "evidence", 0)]:
            with self.subTest(path=path):
                value = copy.deepcopy(self.scan_report)
                target = value
                for part in path:
                    target = target[part]
                target["unexpected"] = True
                with self.assertRaises(ValidationError):
                    ScanReport.model_validate(value)

    def test_repository_normalization(self):
        self.scan_report["system"]["repository_url"] = " https://GitHub.com/x/y.git/ "
        self.assertEqual(ScanReport.model_validate(self.scan_report).system.repository_url,
                         "https://github.com/x/y")

    def test_invalid_or_credentialed_urls(self):
        for url in ["https://", "ftp://example.com/repo", "http://example.com/repo",
                    "https://example.com/repo?q=1", "https://example.com/repo#part",
                    "https://user:secret@example.com/repo", "https://user@example.com/repo"]:
            with self.subTest(url=url):
                self.scan_report["system"]["repository_url"] = url
                with self.assertRaises(ValidationError):
                    ScanReport.model_validate(self.scan_report)

    def test_known_flags_require_real_booleans(self):
        for key in ["sensitive", "writes", "requires_approval"]:
            for value in ["true", 1, None]:
                with self.subTest(key=key, value=value):
                    self.scan_report["components"][0]["attributes"] = {key: value}
                    with self.assertRaises(ValidationError):
                        ScanReport.model_validate(self.scan_report)
            self.scan_report["components"][0]["attributes"] = {key: False}
            ScanReport.model_validate(self.scan_report)

    def test_attributes_require_json_values(self):
        self.scan_report["components"][0]["attributes"] = {"nested": {"items": [1, None, "ok"]}}
        ScanReport.model_validate(self.scan_report)
        self.scan_report["components"][0]["attributes"] = {"date": date(2026, 1, 1)}
        with self.assertRaises(ValidationError):
            ScanReport.model_validate(self.scan_report)

    def test_duplicate_components_after_trimming(self):
        duplicate = copy.deepcopy(self.scan_report["components"][0])
        duplicate["name"] = " refund "
        duplicate["version"] = "2"
        self.scan_report["components"].append(duplicate)
        with self.assertRaises(ValidationError):
            ScanReport.model_validate(self.scan_report)
        duplicate["kind"] = "model"
        ScanReport.model_validate(self.scan_report)

    def test_invalid_evidence_paths(self):
        for path in ["", "   ", "/absolute", "../secret", "app/../secret", "C:/secret", "app\\file.py"]:
            with self.subTest(path=path):
                self.scan_report["components"][0]["evidence"][0]["file_path"] = path
                with self.assertRaises(ValidationError):
                    ScanReport.model_validate(self.scan_report)

    def test_line_ranges(self):
        evidence = self.scan_report["components"][0]["evidence"][0]
        for start, end in [(0, 3), (3, 2), (1, 0)]:
            with self.subTest(start=start, end=end):
                evidence.update(line_start=start, line_end=end)
                with self.assertRaises(ValidationError):
                    ScanReport.model_validate(self.scan_report)
        evidence.update(line_start=1, line_end=1)
        ScanReport.model_validate(self.scan_report)

    def test_hash_formats(self):
        for sha in ["a" * 39, "A" * 40, "g" * 40]:
            with self.subTest(sha=sha), self.assertRaises(ValidationError):
                ScanReport.model_validate({**self.scan_report, "commit_sha": sha})
        evidence = self.scan_report["components"][0]["evidence"][0]
        evidence["snippet_sha256"] = "b" * 64
        ScanReport.model_validate(self.scan_report)
        evidence["snippet_sha256"] = "invalid"
        with self.assertRaises(ValidationError):
            ScanReport.model_validate(self.scan_report)

    def test_allowed_categories_and_positive_owner(self):
        for key, value in [("environment", "test"), ("owner_user_id", 0)]:
            with self.subTest(key=key):
                scan_report = copy.deepcopy(self.scan_report)
                scan_report["system"][key] = value
                with self.assertRaises(ValidationError):
                    ScanReport.model_validate(scan_report)
        self.scan_report["components"][0]["kind"] = "unknown"
        with self.assertRaises(ValidationError):
            ScanReport.model_validate(self.scan_report)

    def test_collection_limits(self):
        component = self.scan_report["components"][0]
        component["evidence"] *= 101
        with self.assertRaises(ValidationError):
            ScanReport.model_validate(self.scan_report)
        component["evidence"] = component["evidence"][:1]
        self.scan_report["components"] = [
            {**copy.deepcopy(component), "name": f"tool-{index}"}
            for index in range(501)
        ]
        with self.assertRaises(ValidationError):
            ScanReport.model_validate(self.scan_report)

    def test_string_limits_and_blank_names(self):
        for value in [" " * 3, "x" * 201]:
            with self.subTest(value=value):
                self.scan_report["components"][0]["name"] = value
                with self.assertRaises(ValidationError):
                    ScanReport.model_validate(self.scan_report)


if __name__ == "__main__":
    unittest.main()
