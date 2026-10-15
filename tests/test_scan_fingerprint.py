"""Check scan identity without database or network dependencies."""

import copy
import json
import re
import unittest

from app.schemas import ScanReport
from app.services.scans import fingerprint_scan


class ScanFingerprintTests(unittest.TestCase):
    def setUp(self):
        evidence = {"file_path": "app/llm.py", "line_start": 3,
                    "line_end": 3, "detector": "import-scan"}
        self.data = {
            "system": {"name": "support-bot", "repository_url": "https://example.com/repo",
                       "environment": "prod"},
            "commit_sha": "a" * 40,
            "components": [
                {"kind": "vendor", "name": "example-vendor", "evidence": [
                    {**evidence, "snippet_sha256": "a" * 64},
                    {**evidence, "snippet_sha256": "b" * 64},
                ]},
                {"kind": "tool", "name": "refund", "evidence": [evidence],
                 "attributes": {"writes": True, "config": {"a": 1, "b": 2},
                                "steps": ["review", "execute"]}},
            ],
        }

    def fingerprint(self, data):
        return fingerprint_scan(ScanReport.model_validate(data))

    def test_repeatable_sha256(self):
        result = self.fingerprint(self.data)
        self.assertRegex(result, re.compile(r"^[0-9a-f]{64}$"))
        self.assertEqual(result, self.fingerprint(self.data))

    def test_json_format_and_object_key_order_do_not_matter(self):
        compact = ScanReport.model_validate_json(json.dumps(self.data, separators=(",", ":")))
        reordered = ScanReport.model_validate_json(json.dumps(self.data, sort_keys=True, indent=4))
        self.assertEqual(fingerprint_scan(compact), fingerprint_scan(reordered))

    def test_component_and_evidence_order_do_not_matter(self):
        reordered = copy.deepcopy(self.data)
        # Evidence locations tie: snippet hashes must participate in sorting.
        reordered["components"][0]["evidence"].reverse()
        reordered["components"].reverse()
        self.assertEqual(self.fingerprint(self.data), self.fingerprint(reordered))

    def test_meaningful_changes_change_fingerprint(self):
        original = self.fingerprint(self.data)
        changes = [
            (("commit_sha",), "b" * 40),
            (("system", "environment"), "dev"),
            (("system", "owner_user_id"), 1),
            (("components", 0, "version"), "2"),
            (("components", 0, "evidence", 0, "snippet_sha256"), "c" * 64),
            (("components", 0, "evidence", 0, "line_end"), 4),
            (("components", 1, "attributes", "writes"), False),
        ]
        for path, value in changes:
            with self.subTest(path=path):
                changed = copy.deepcopy(self.data)
                target = changed
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                self.assertNotEqual(original, self.fingerprint(changed))

    def test_attribute_list_order_is_preserved(self):
        changed = copy.deepcopy(self.data)
        changed["components"][1]["attributes"]["steps"].reverse()
        self.assertNotEqual(self.fingerprint(self.data), self.fingerprint(changed))

    def test_input_model_is_not_mutated(self):
        report = ScanReport.model_validate(self.data)
        before = report.model_dump(mode="json")
        fingerprint_scan(report)
        self.assertEqual(report.model_dump(mode="json"), before)

    def test_defaults_and_normalized_urls_have_same_fingerprint(self):
        explicit = ScanReport.model_validate(self.data).model_dump(mode="json")
        explicit["system"]["repository_url"] += ".git/"
        self.assertEqual(self.fingerprint(self.data), self.fingerprint(explicit))

    def test_empty_and_omitted_components_are_equivalent(self):
        empty = {**self.data, "components": []}
        omitted = {key: value for key, value in empty.items() if key != "components"}
        self.assertEqual(self.fingerprint(empty), self.fingerprint(omitted))

    def test_duplicate_evidence_is_not_silently_discarded(self):
        changed = copy.deepcopy(self.data)
        changed["components"][0]["evidence"].append(copy.deepcopy(changed["components"][0]["evidence"][0]))
        self.assertNotEqual(self.fingerprint(self.data), self.fingerprint(changed))


if __name__ == "__main__":
    unittest.main()
