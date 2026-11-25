from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from ovo_acceptance import resolution

ROOT = Path(__file__).resolve().parents[1]


def problem(kind="auto_fix", effect="none"):
    return {
        "schema": "ovo.problem-resolution/1", "problem_id": "problem-1",
        "product": "growovo", "task_id": "task-1", "observed_at": "2026-11-25T00:00:00Z",
        "observation": {"code": "CHANNEL_TIMEOUT", "summary": "The local channel timed out.",
                        "external_effect_status": effect, "evidence_refs": ["trace-1"]},
        "requested_resolution": kind,
        "fix": {"action_id": "retry-local-read", "side_effect_free": True,
                "same_authorization": True, "max_attempts": 1},
    }


class ProblemResolutionTest(unittest.TestCase):
    def test_side_effect_free_auto_fix_is_ready_but_not_applied(self):
        result = resolution.evaluate(problem())
        self.assertEqual("READY", result["status"])
        self.assertEqual("auto_fix", result["resolution"])
        self.assertTrue(result["automatic_action_allowed"])
        self.assertFalse(result["execution_applied"])
        self.assertEqual("retry-local-read", result["action"]["action_id"])

    def test_unknown_external_effect_requires_reconciliation_before_retry(self):
        result = resolution.evaluate(problem(effect="unknown"))
        self.assertEqual("RECONCILE_REQUIRED", result["status"])
        self.assertEqual("reconcile_external_result", result["next_action"])
        self.assertFalse(result["automatic_action_allowed"])
        self.assertFalse(result["execution_applied"])

    def test_alternative_path_must_be_verified_compliant_and_in_scope(self):
        doc = problem("switch_path")
        doc["alternative"] = {
            "path_id": "official-api", "verified": True, "compliant": False,
            "same_scope": True, "authorization_refs": ["grant-1"],
        }
        with self.assertRaisesRegex(ValueError, "compliant"):
            resolution.evaluate(doc)

    def test_missing_data_is_fetched_before_asking_the_user(self):
        doc = problem("data_needed")
        doc["data"] = {"request_id": "data-1", "source": "authorized-local-export",
                       "access_basis": "buyer-owned export", "automatic_fetch_attempted": False,
                       "side_effect_free_fetch": True}
        first = resolution.evaluate(doc)
        self.assertEqual("fetch_data", first["next_action"])
        self.assertFalse(first["user_prompt_required"])
        doc["data"]["automatic_fetch_attempted"] = True
        second = resolution.evaluate(doc)
        self.assertEqual("NEEDS_USER_INPUT", second["status"])
        self.assertEqual("request_data", second["next_action"])
        self.assertTrue(second["user_prompt_required"])

    def test_partial_delivery_must_keep_limits_visible(self):
        doc = problem("partial_delivery")
        doc["partial"] = {"deliverable_refs": ["partial-report"], "limitations": [],
                          "completion_claim": "partial"}
        with self.assertRaisesRegex(ValueError, "limitations"):
            resolution.evaluate(doc)

    def test_cli_evaluates_example(self):
        result = subprocess.run([
            sys.executable, "-m", "ovo_acceptance", "resolution",
            str(ROOT / "examples/problem-resolution.json"), "--json",
        ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("ovo.problem-resolution-result/1", payload["schema"])
        self.assertFalse(payload["execution_applied"])


if __name__ == "__main__":
    unittest.main()
