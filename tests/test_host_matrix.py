from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from ovo_acceptance import host_matrix

ROOT = Path(__file__).resolve().parents[1]


def observation(capability="high_level_task", status="PASS"):
    return {"host": "fixture-host", "model": "fixture-model", "product": "askovo",
            "capability": capability, "status": status, "run_ref": "run-1",
            "evidence_ref": "evidence/run-1"}


class HostCompatibilityMatrixTest(unittest.TestCase):
    def test_summary_separates_measured_not_run_and_capability_only(self):
        result = host_matrix.summarize({
            "schema": "ovo.host-compatibility/1", "matrix_id": "matrix-1",
            "observations": [observation(), observation("natural_language_delivery"),
                             observation("background_execution", "CAPABILITY_ONLY"),
                             observation("mcp_call", "NOT_RUN")],
        })
        self.assertEqual("ovo.host-compatibility-result/1", result["schema"])
        self.assertEqual(2, result["summary"]["PASS"])
        self.assertEqual(1, result["summary"]["CAPABILITY_ONLY"])
        self.assertEqual(1, result["summary"]["NOT_RUN"])
        host = result["hosts"][0]
        self.assertEqual("PASS", host["core_l3_status"])
        self.assertEqual("CAPABILITY_ONLY", host["continuous_runtime_status"])
        self.assertEqual(3, host["coverage"]["measured_or_capability_observations"])

    def test_pass_requires_run_and_evidence_references(self):
        row = observation()
        row["run_ref"] = ""
        with self.assertRaisesRegex(ValueError, "run_ref"):
            host_matrix.summarize({"schema": "ovo.host-compatibility/1", "matrix_id": "m1",
                                   "observations": [row]})

    def test_capability_only_never_becomes_continuous_pass(self):
        result = host_matrix.summarize({
            "schema": "ovo.host-compatibility/1", "matrix_id": "m1",
            "observations": [observation("background_execution", "CAPABILITY_ONLY")],
        })
        self.assertNotEqual("PASS", result["hosts"][0]["continuous_runtime_status"])

    def test_duplicate_host_capability_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            host_matrix.summarize({"schema": "ovo.host-compatibility/1", "matrix_id": "m1",
                                   "observations": [observation(), observation()]})

    def test_cli_summarizes_example_without_claiming_real_l3(self):
        result = subprocess.run([
            sys.executable, "-m", "ovo_acceptance", "host-matrix",
            str(ROOT / "examples/host-compatibility.json"), "--json",
        ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("ovo.host-compatibility-result/1", payload["schema"])
        self.assertEqual("INCOMPLETE", payload["hosts"][0]["core_l3_status"])


if __name__ == "__main__":
    unittest.main()
