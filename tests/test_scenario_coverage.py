from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ovo_acceptance import scenario_coverage

ROOT = Path(__file__).resolve().parents[1]


def scenario(scenario_id="A-S01", acceptance="not_run"):
    product = {"A": "askovo", "G": "growovo", "V": "verovo"}[scenario_id[0]]
    accepted = acceptance in {"accepted_real", "accepted_external"}
    return {
        "scenario_id": scenario_id, "product": product, "title": "Scenario " + scenario_id,
        "entrypoints": ["askovo decide" if product == "askovo" else product + " scenario"],
        "implementation_status": "local" if accepted else "partial",
        "acceptance_status": acceptance,
        "existing_evidence": ["existing local capability"],
        "test_refs": ["tests/test_example.py"],
        "case_refs": ["CASE-01"] if accepted else [],
        "missing": [] if accepted else ["Real business acceptance is still required."],
    }


class ScenarioCoverageTest(unittest.TestCase):
    def test_summary_separates_implementation_from_acceptance(self):
        result = scenario_coverage.summarize({
            "schema": "ovo.business-scenario-catalog/1", "catalog_id": "test-catalog",
            "source_ref": "fixture", "scenarios": [
                scenario("A-S01", "accepted_external"), scenario("G-S01", "not_run")],
        })
        self.assertEqual(2, result["coverage"]["total"])
        self.assertEqual(1, result["coverage"]["accepted_external"])
        self.assertEqual(1, result["coverage"]["not_accepted"])
        self.assertEqual(1, result["coverage"]["by_product"]["askovo"])
        self.assertEqual(1, result["coverage"]["by_product"]["growovo"])

    def test_acceptance_requires_cases_and_no_open_missing_conditions(self):
        row = scenario("V-S06", "accepted_real")
        row["missing"] = ["Unverified condition"]
        with self.assertRaisesRegex(ValueError, "missing"):
            scenario_coverage.summarize({
                "schema": "ovo.business-scenario-catalog/1", "catalog_id": "bad",
                "source_ref": "fixture", "scenarios": [row],
            })
        row["missing"] = []
        row["case_refs"] = []
        with self.assertRaisesRegex(ValueError, "case_refs"):
            scenario_coverage.summarize({
                "schema": "ovo.business-scenario-catalog/1", "catalog_id": "bad",
                "source_ref": "fixture", "scenarios": [row],
            })

    def test_duplicate_and_product_mismatch_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            scenario_coverage.summarize({
                "schema": "ovo.business-scenario-catalog/1", "catalog_id": "bad",
                "source_ref": "fixture", "scenarios": [scenario(), scenario()],
            })
        row = scenario("G-S02")
        row["product"] = "askovo"
        with self.assertRaisesRegex(ValueError, "product"):
            scenario_coverage.summarize({
                "schema": "ovo.business-scenario-catalog/1", "catalog_id": "bad",
                "source_ref": "fixture", "scenarios": [row],
            })

    def test_cli_outputs_coverage_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps({
                "schema": "ovo.business-scenario-catalog/1", "catalog_id": "test-catalog",
                "source_ref": "fixture", "scenarios": [scenario()],
            }), encoding="utf-8")
            result = subprocess.run([
                sys.executable, "-m", "ovo_acceptance", "scenario-coverage", str(path), "--json",
            ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(1, payload["coverage"]["not_accepted"])
        self.assertIn("not product completion", payload["boundary"])


if __name__ == "__main__":
    unittest.main()
