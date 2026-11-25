from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ovo_acceptance import experience

ROOT = Path(__file__).resolve().parents[1]


def run(run_id, outcome="REAL_SUCCESS", input_class="real_authorized"):
    return {
        "schema": "ovo.agent-e2e-run/1", "run_id": run_id, "case_id": "A-E2E-01",
        "arm": "product", "product": "askovo", "input_class": input_class,
        "agent": {"host": "fixture-host", "model": "fixture-model", "session_ref": run_id + "-session"},
        "fresh_session": True, "natural_language_task": True, "solution_hints_provided": False,
        "started_at": "2026-11-25T00:00:00Z", "finished_at": "2026-11-25T00:10:00Z",
        "outcome": outcome, "external_result_observed": False,
        "evidence": {"session_transcript_ref": run_id + "-transcript",
                     "tool_trace_ref": run_id + "-trace",
                     "deliverable_refs": [run_id + "-deliverable"] if outcome == "REAL_SUCCESS" else [],
                     "human_review_ref": run_id + "-review"},
        "human_review": {"reviewed_by": "buyer-owner", "reviewed_at": "2026-11-25T00:11:00Z",
                         "accepted": outcome == "REAL_SUCCESS", "minutes": 1},
        "defect_ids": ["D1"] if outcome == "INCORRECT_DELIVERY" else [],
        "notes": "synthetic test configuration" if input_class == "synthetic" else "",
    }


def effort(minutes):
    return {"total_minutes": minutes, "authorization_minutes": 1,
            "business_input_minutes": 1, "product_issue_minutes": 0}


class ExperienceSummaryTest(unittest.TestCase):
    def test_low_touch_rate_keeps_high_touch_success_in_denominator(self):
        result = experience.summarize({
            "runs": [run("run-01"), run("run-02")], "human_limits": {"A-E2E-01": 10},
            "effort": {"run-01": effort(5), "run-02": effort(20)}, "failures": [],
        })
        self.assertEqual(2, result["eligible_started"])
        self.assertEqual(1, result["accepted_low_touch"])
        self.assertEqual(0.5, result["low_touch_accepted_delivery_rate"])

    def test_installation_failure_is_counted_and_classified(self):
        result = experience.summarize({
            "runs": [run("run-01"), run("run-02", "INCORRECT_DELIVERY")],
            "human_limits": {"A-E2E-01": 10},
            "effort": {"run-01": effort(5), "run-02": effort(5)},
            "failures": [{"run_id": "run-02", "category": "installation_failure", "defect_id": "D1"}],
        })
        self.assertEqual(2, result["eligible_started"])
        self.assertEqual(1, result["failure_taxonomy"]["installation_failure"])

    def test_missing_effort_does_not_become_zero_touch(self):
        result = experience.summarize({
            "runs": [run("run-01")], "human_limits": {"A-E2E-01": 10},
            "effort": {}, "failures": [],
        })
        self.assertEqual(0, result["accepted_low_touch"])
        self.assertEqual(1, result["coverage"]["missing_effort"])

    def test_synthetic_runs_are_separate_from_real_rate(self):
        result = experience.summarize({
            "runs": [run("syn-01", "JUSTIFIED_REFUSAL", "synthetic")],
            "human_limits": {}, "effort": {}, "failures": [],
        })
        self.assertEqual(0, result["eligible_started"])
        self.assertIsNone(result["low_touch_accepted_delivery_rate"])
        self.assertEqual(1, result["non_real_observations"])

    def test_unknown_failure_category_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "category"):
            experience.summarize({
                "runs": [run("run-01")], "human_limits": {"A-E2E-01": 10},
                "effort": {"run-01": effort(5)},
                "failures": [{"run_id": "run-01", "category": "unknown", "defect_id": "D1"}],
            })

    def test_cli_summarizes_example(self):
        result = subprocess.run([
            sys.executable, "-m", "ovo_acceptance", "experience",
            str(ROOT / "examples/experience-summary.json"), "--json",
        ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("ovo.experience-summary/1", payload["schema"])


if __name__ == "__main__":
    unittest.main()
