from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from ovo_acceptance import model_upgrade

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "valid-model-upgrade.json"


def load():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class ModelUpgradeTest(unittest.TestCase):
    def test_higher_better_gain_is_amplified(self):
        result = model_upgrade.compare(load())
        self.assertEqual("ELIGIBLE", result["status"])
        self.assertEqual(2, result["gains"]["product_with_weak_model"])
        self.assertEqual(5, result["gains"]["product_with_strong_model"])
        self.assertEqual(3, result["gains"]["amplification"])
        self.assertEqual("amplified", result["classification"])
        self.assertEqual("not_claimed", result["causality"])

    def test_lower_better_normalizes_direction(self):
        doc = load()
        doc["metric"]["direction"] = "lower_better"
        for key, value in (("weak_without_product", 10), ("weak_with_product", 8),
                           ("strong_without_product", 6), ("strong_with_product", 3)):
            doc["arms"][key]["value"] = value
        result = model_upgrade.compare(doc)
        self.assertEqual(2, result["gains"]["product_with_weak_model"])
        self.assertEqual(3, result["gains"]["product_with_strong_model"])
        self.assertEqual("amplified", result["classification"])

    def test_shrinking_gain_is_diminishing_not_a_product_verdict(self):
        doc = load()
        doc["arms"]["weak_with_product"]["value"] = 8
        doc["arms"]["strong_without_product"]["value"] = 9
        doc["arms"]["strong_with_product"]["value"] = 10
        result = model_upgrade.compare(doc)
        self.assertEqual("diminishing", result["classification"])
        self.assertIn("single_task", result["evidence_strength"])
        self.assertNotIn("boat", json.dumps(result).lower())

    def test_tolerance_can_keep_change_stable(self):
        doc = load()
        doc["arms"]["strong_with_product"]["value"] = 7.05
        doc["metric"]["tolerance"] = 0.1
        result = model_upgrade.compare(doc)
        self.assertEqual("stable", result["classification"])

    def test_ineligible_comparison_does_not_emit_gains(self):
        doc = load()
        doc["comparability"]["same_acceptance_rubric"] = False
        result = model_upgrade.compare(doc)
        self.assertEqual("INELIGIBLE", result["status"])
        self.assertEqual("not_assessed", result["classification"])
        self.assertIsNone(result["gains"])

    def test_four_fresh_unique_runs_are_required(self):
        doc = copy.deepcopy(load())
        doc["arms"]["strong_with_product"]["run_ref"] = doc["arms"]["weak_without_product"]["run_ref"]
        with self.assertRaisesRegex(ValueError, "unique"):
            model_upgrade.compare(doc)

    def test_cli_compares_example(self):
        result = subprocess.run([
            sys.executable, "-m", "ovo_acceptance", "model-upgrade", str(EXAMPLE), "--json",
        ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("amplified", payload["classification"])


if __name__ == "__main__":
    unittest.main()
