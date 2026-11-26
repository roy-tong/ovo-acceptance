from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from ovo_acceptance import model

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class C01ContractTests(unittest.TestCase):
    def test_valid_result_receipt(self) -> None:
        doc = load("valid-result-receipt.json")
        self.assertEqual([], model.validate_document(doc))

    def test_valid_delegated_task(self) -> None:
        doc = load("valid-delegated-task.json")
        self.assertEqual([], model.validate_document(doc))

    def test_valid_service_capability(self) -> None:
        doc = load("valid-service-capability.json")
        self.assertEqual([], model.validate_document(doc))

    def test_valid_task_result(self) -> None:
        doc = load("valid-task-result.json")
        self.assertEqual([], model.validate_document(doc))

    def test_needs_decision_requires_the_decision_flag(self) -> None:
        doc = load("valid-task-result.json")
        doc["status"] = "needs_decision"
        errors = model.validate_document(doc)
        self.assertIn("DECISION_FLAG_CONFLICT", [item["code"] for item in errors])

    def test_completed_cannot_have_a_blocking_missing_condition(self) -> None:
        doc = load("valid-task-result.json")
        doc["status"] = "completed"
        doc["missing_conditions"] = [{
            "code": "AUTHORIZATION_REQUIRED", "detail": "deployment is not authorized",
            "scope": "deployment", "blocking": True,
        }]
        errors = model.validate_document(doc)
        self.assertIn("COMPLETED_WITH_BLOCKER", [item["code"] for item in errors])

    def test_partial_result_must_include_an_actual_result(self) -> None:
        doc = load("valid-task-result.json")
        doc["status"] = "partial_result"
        doc["completed"] = []
        doc["evidence_refs"] = []
        errors = model.validate_document(doc)
        self.assertIn("PARTIAL_WITHOUT_RESULT", [item["code"] for item in errors])

    def test_unable_to_complete_needs_a_recovery_action(self) -> None:
        doc = load("valid-task-result.json")
        doc["status"] = "unable_to_complete"
        doc["next_actions"] = []
        errors = model.validate_document(doc)
        self.assertIn("RECOVERY_REQUIRED", [item["code"] for item in errors])

    def test_business_outcome_needs_human_acceptance(self) -> None:
        doc = load("valid-result-receipt.json")
        doc["verification_state"] = "verified_business_outcome"
        doc["human_review"] = {"reviewed_by": "demo-reviewer", "accepted": False}
        errors = model.validate_document(doc)
        self.assertIn("BUSINESS_OUTCOME_WITHOUT_REVIEW",
                      [item["code"] for item in errors])

    def test_observed_time_cannot_precede_occurrence(self) -> None:
        doc = load("valid-result-receipt.json")
        doc["observed_at"] = "2026-11-24T08:00:00Z"
        errors = model.validate_document(doc)
        self.assertIn("TIME_ORDER", [item["code"] for item in errors])

    def test_empty_authorization_cannot_be_running(self) -> None:
        doc = load("valid-delegated-task.json")
        doc["authorization_ref"] = ""
        doc["state"] = "running"
        errors = model.validate_document(doc)
        self.assertIn("AUTH_STATE_CONFLICT", [item["code"] for item in errors])

    def test_production_proven_needs_evidence(self) -> None:
        doc = load("valid-service-capability.json")
        doc["maturity"] = "production_proven"
        doc.pop("evidence_refs", None)
        errors = model.validate_document(doc)
        self.assertIn("MATURITY_WITHOUT_EVIDENCE",
                      [item["code"] for item in errors])

    def test_unknown_fields_are_rejected(self) -> None:
        doc = copy.deepcopy(load("valid-delegated-task.json"))
        doc["surprise"] = True
        errors = model.validate_document(doc)
        self.assertIn("UNKNOWN_FIELD", [item["code"] for item in errors])

    def test_cli_autodetects_all_three(self) -> None:
        for name in ("valid-result-receipt.json", "valid-delegated-task.json",
                     "valid-service-capability.json", "valid-task-result.json"):
            result = subprocess.run(
                [sys.executable, "-m", "ovo_acceptance", "validate",
                 str(EXAMPLES / name), "--json"],
                cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload)


if __name__ == "__main__":
    unittest.main()
