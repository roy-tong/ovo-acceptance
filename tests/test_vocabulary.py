from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from ovo_acceptance import vocabulary

ROOT = Path(__file__).resolve().parents[1]


class FamilyVocabularyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = vocabulary.load_vocabulary()

    def test_current_map_is_valid(self) -> None:
        self.assertEqual([], vocabulary.validate_vocabulary(self.doc))

    def test_all_three_products_are_mapped(self) -> None:
        products = (self.doc.get("lifecycle") or {}).get("products", {})
        self.assertEqual({"askovo", "growovo", "verovo"}, set(products))

    def test_state_and_verdict_translation(self) -> None:
        self.assertEqual("awaiting_authorization",
                         vocabulary.translate_state("askovo", "scoped", self.doc))
        self.assertEqual("needs_review",
                         vocabulary.translate_state("growovo", "needs_attention", self.doc))
        self.assertEqual("UNPROVEN",
                         vocabulary.translate_verdict("proof", "UNCHECKED", self.doc))
        self.assertEqual("PASS_WITH_GAP",
                         vocabulary.translate_verdict("bundle", "PASS_WITH_GAP", self.doc))

    def test_unknown_target_is_rejected(self) -> None:
        broken = copy.deepcopy(self.doc)
        broken["lifecycle"]["products"]["askovo"]["created"] = "made_up"
        errors = vocabulary.validate_vocabulary(broken)
        self.assertTrue(any("unknown canonical state" in item for item in errors), errors)

    def test_unknown_verdict_target_is_rejected(self) -> None:
        broken = copy.deepcopy(self.doc)
        broken["verdicts"]["sources"]["proof"]["PASS"] = "MAYBE"
        errors = vocabulary.validate_vocabulary(broken)
        self.assertTrue(any("unknown canonical verdict" in item for item in errors), errors)
        errors = vocabulary.validate_vocabulary(broken)
        self.assertTrue(any("unknown canonical verdict" in item for item in errors), errors)

    def test_cli_reports_the_map(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ovo_acceptance", "vocabulary", "--json"],
            cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertIn("verovo", payload["products"])
        self.assertEqual(11, payload["lifecycle_states"])


if __name__ == "__main__":
    unittest.main()
