from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from ovo_acceptance import model

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "valid-experiment-contract.json"


def load() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class ExperimentContractTests(unittest.TestCase):
    def test_valid_experiment_autodetects_and_validates(self) -> None:
        doc = load()
        self.assertEqual("experiment", model.detect_kind(doc))
        self.assertEqual([], model.validate_document(doc))

    def test_cli_autodetects_experiment(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ovo_acceptance", "validate",
             str(EXAMPLE), "--json"],
            cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("experiment", payload["kind"])
        self.assertTrue(payload["ok"], payload)

    def test_design_change_invalidates_registration_fingerprint(self) -> None:
        doc = load()
        doc["design"]["arms"][0]["planned_sample_size"] = 99
        errors = model.validate_document(doc)
        self.assertIn("DESIGN_FINGERPRINT_MISMATCH",
                      [item["code"] for item in errors])

    def test_observation_must_reference_registered_arm_and_metric(self) -> None:
        doc = load()
        doc["observations"][0]["arm_id"] = "missing-arm"
        doc["observations"][0]["metric_id"] = "missing-metric"
        codes = [item["code"] for item in model.validate_document(doc)]
        self.assertIn("UNKNOWN_ARM", codes)
        self.assertIn("UNKNOWN_METRIC", codes)

    def test_external_action_requires_authorization(self) -> None:
        doc = load()
        doc["external_actions"] = True
        doc["authorization_refs"] = []
        errors = model.validate_document(doc)
        self.assertIn("EXTERNAL_ACTION_WITHOUT_AUTHORIZATION",
                      [item["code"] for item in errors])

    def test_descriptive_result_cannot_claim_causality(self) -> None:
        doc = load()
        doc["outcome"]["causality"] = "causal_supported"
        errors = model.validate_document(doc)
        self.assertIn("CAUSAL_DESIGN_INSUFFICIENT",
                      [item["code"] for item in errors])

    def test_decisive_outcome_requires_eligible_primary_evidence(self) -> None:
        doc = load()
        doc["outcome"]["evidence_refs"] = []
        errors = model.validate_document(doc)
        self.assertIn("OUTCOME_WITHOUT_EVIDENCE",
                      [item["code"] for item in errors])

    def test_excluded_observation_requires_reason(self) -> None:
        doc = load()
        doc["observations"][0]["eligible"] = False
        codes = [item["code"] for item in model.validate_document(doc)]
        self.assertIn("EXCLUSION_REASON_REQUIRED", codes)

    def test_window_must_be_ordered(self) -> None:
        doc = load()
        doc["window"]["end"] = doc["window"]["start"]
        errors = model.validate_document(doc)
        self.assertIn("TIME_ORDER", [item["code"] for item in errors])

    def test_causal_result_requires_randomized_comparable_control(self) -> None:
        doc = load()
        doc["design"]["assignment"] = "randomized"
        doc["outcome"]["causality"] = "causal_supported"
        doc["design_sha256"] = model.experiment_design_hash(doc)
        self.assertEqual([], model.validate_document(doc))
        doc["design"]["comparability"]["same_acceptance_rubric"] = False
        doc["design_sha256"] = model.experiment_design_hash(doc)
        codes = [item["code"] for item in model.validate_document(doc)]
        self.assertIn("CAUSAL_DESIGN_INSUFFICIENT", codes)

    def test_arm_price_is_structured_and_fingerprinted(self) -> None:
        doc = load()
        doc["design"]["arms"][0]["price"] = {
            "amount": 10, "currency": "USD", "definition": "Monthly subscription displayed before registration"}
        doc["design_sha256"] = model.experiment_design_hash(doc)
        self.assertEqual([], model.validate_document(doc))
        doc["design"]["arms"][0]["price"]["amount"] = 20
        codes = [item["code"] for item in model.validate_document(doc)]
        self.assertIn("DESIGN_FINGERPRINT_MISMATCH", codes)

    def test_invalid_arm_price_is_rejected(self) -> None:
        doc = load()
        doc["design"]["arms"][0]["price"] = {
            "amount": -1, "currency": "USD", "definition": "Monthly subscription"}
        doc["design_sha256"] = model.experiment_design_hash(doc)
        self.assertTrue(model.validate_document(doc))

    def test_unknown_fields_are_rejected(self) -> None:
        doc = copy.deepcopy(load())
        doc["surprise"] = True
        errors = model.validate_document(doc)
        self.assertIn("UNKNOWN_FIELD", [item["code"] for item in errors])


if __name__ == "__main__":
    unittest.main()
