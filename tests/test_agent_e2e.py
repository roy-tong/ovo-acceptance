from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from ovo_acceptance import model

ROOT = Path(__file__).resolve().parents[1]


def _codes(errors):
    return [item["code"] for item in errors]


def _example():
    return model.load_json(ROOT / "examples" / "agent-e2e-refusal.json")


def _real_success():
    doc = _example()
    doc["input_class"] = "real_authorized"
    doc["outcome"] = "REAL_SUCCESS"
    doc["evidence"]["deliverable_refs"] = ["artifacts/decision-brief.md"]
    doc["human_review"]["accepted"] = True
    return doc


class AgentE2ERunTest(unittest.TestCase):
    def test_synthetic_refusal_example_is_valid(self):
        self.assertEqual([], model.validate_document(_example()))

    def test_real_success_with_real_inputs_and_human_acceptance_is_valid(self):
        self.assertEqual([], model.validate_document(_real_success()))

    def test_synthetic_input_cannot_be_real_success(self):
        doc = _real_success()
        doc["input_class"] = "synthetic"
        self.assertIn("SYNTHETIC_NOT_REAL_SUCCESS", _codes(model.validate_document(doc)))

    def test_success_requires_human_acceptance(self):
        doc = _real_success()
        doc["human_review"]["accepted"] = False
        self.assertIn("SUCCESS_WITHOUT_HUMAN_ACCEPTANCE", _codes(model.validate_document(doc)))

    def test_success_requires_final_deliverable(self):
        doc = _real_success()
        doc["evidence"]["deliverable_refs"] = []
        self.assertIn("SUCCESS_WITHOUT_DELIVERABLE", _codes(model.validate_document(doc)))

    def test_success_cannot_carry_open_defects(self):
        doc = _real_success()
        doc["defect_ids"] = ["A-P0-1"]
        self.assertIn("SUCCESS_WITH_OPEN_DEFECTS", _codes(model.validate_document(doc)))

    def test_growovo_success_requires_external_observation_and_receipt(self):
        doc = _real_success()
        doc["case_id"] = "G-E2E-01"
        doc["product"] = "growovo"
        codes = _codes(model.validate_document(doc))
        self.assertIn("GROWOVO_EXTERNAL_RESULT_REQUIRED", codes)
        self.assertIn("GROWOVO_RECEIPT_REQUIRED", codes)
        doc["external_result_observed"] = True
        doc["evidence"]["external_receipt_refs"] = ["receipts/platform-001.json"]
        self.assertEqual([], model.validate_document(doc))

    def test_incorrect_delivery_requires_tracked_defect(self):
        doc = _example()
        doc["outcome"] = "INCORRECT_DELIVERY"
        self.assertIn("INCORRECT_WITHOUT_DEFECT", _codes(model.validate_document(doc)))
        doc["defect_ids"] = ["A-P0-1"]
        self.assertEqual([], model.validate_document(doc))

    def test_refusal_and_takeover_keep_their_reason_and_human_cost(self):
        doc = _example()
        doc["notes"] = ""
        self.assertIn("REFUSAL_NEEDS_REASON", _codes(model.validate_document(doc)))
        doc = _example()
        doc["outcome"] = "HUMAN_TAKEOVER"
        doc["human_review"]["minutes"] = 0
        self.assertIn("TAKEOVER_NEEDS_TIME", _codes(model.validate_document(doc)))

    def test_time_order_is_checked(self):
        doc = _example()
        doc["finished_at"] = doc["started_at"]
        doc["started_at"] = "2026-11-22T11:00:00+08:00"
        self.assertIn("TIME_ORDER", _codes(model.validate_document(doc)))


class AgentE2ECaseMatrixTest(unittest.TestCase):
    def test_nine_cases_cover_three_products_and_require_paired_arms(self):
        matrix = json.loads((ROOT / "e2e" / "cases.json").read_text(encoding="utf-8"))
        cases = matrix["cases"]
        self.assertEqual(9, len(cases))
        self.assertEqual(9, len({case["case_id"] for case in cases}))
        for product in ("askovo", "growovo", "verovo"):
            self.assertEqual(3, len([case for case in cases if case["product"] == product]))
        self.assertIn("product and baseline", matrix["run_rule"])
        self.assertEqual("REVIEW_REQUIRED", matrix["status"])
        self.assertEqual("2026-11-27", matrix["last_run"])
        self.assertIn("九类Agent-E2E-20261127", matrix["review_pack"])

    def test_growovo_cases_require_external_receipts(self):
        matrix = json.loads((ROOT / "e2e" / "cases.json").read_text(encoding="utf-8"))
        for case in matrix["cases"]:
            if case["product"] == "growovo":
                self.assertTrue(case["external_receipt_required"])


if __name__ == "__main__":
    unittest.main()
