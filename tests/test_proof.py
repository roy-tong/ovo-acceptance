from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ovo_acceptance import model  # noqa: E402
from ovo_acceptance import proof  # noqa: E402
from test_acceptance import CONTRACT_ID, T, _valid_bundle  # noqa: E402


class ProofBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proof-bundle"
        self.root.mkdir()
        self.bundle = _valid_bundle()
        (self.root / "bundle.json").write_text(
            json.dumps(self.bundle), encoding="utf-8")
        (self.root / "contract.json").write_text(
            json.dumps(self.bundle["task_contract"]), encoding="utf-8")
        self._write_trace()
        artifact = self.root / "artifacts" / "brief.md"
        artifact.parent.mkdir()
        artifact.write_text("decision brief\n", encoding="utf-8")
        self.artifact_hash = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
        (self.root / "proof.json").write_text(json.dumps({
            "schema": proof.PROOF_SCHEMA,
            "proof_id": "proof-001",
            "contract_id": CONTRACT_ID,
            "product": "askovo",
            "generated_at": T,
            "environment": {
                "product_version": "2.20.3",
                "runtime": "Python 3.9",
                "platform": "test",
            },
            "artifacts": [{
                "artifact_id": "brief",
                "path": "artifacts/brief.md",
                "sha256": self.artifact_hash,
                "classification": "synthetic",
            }],
            "replay": {
                "manifest": "replay/manifest.json",
                "status": "AVAILABLE",
                "missing": [],
            },
            "limitations": ["synthetic example"],
        }), encoding="utf-8")
        replay = self.root / "replay" / "manifest.json"
        replay.parent.mkdir()
        replay.write_text(json.dumps({
            "schema": proof.REPLAY_SCHEMA,
            "contract_id": CONTRACT_ID,
            "status": "AVAILABLE",
            "commands": [{"name": "validate", "argv": ["python3", "-m", "ovo_acceptance", "bundle", "bundle.json"]}],
            "inputs": [{"ref": "bundle.json", "sha256": "sha256:" + "b" * 64}],
            "missing": [],
        }), encoding="utf-8")
        self.checks = {
            "schema": proof.CHECKS_SCHEMA,
            "contract_id": CONTRACT_ID,
            "checks": [self._check("c1", "P1")],
        }
        self._write_checks()

    def tearDown(self):
        self.tmp.cleanup()

    def _check(self, check_id="c1", level="P1", status="PASS"):
        independence = {
            "P0": proof.EXECUTOR_OBSERVED,
            "P1": proof.EXECUTOR_OBSERVED,
            "P2": proof.INDEPENDENT_STATE,
            "P3": proof.INDEPENDENT_VALIDATOR,
            "P4": proof.EXTERNAL_OBSERVATION,
        }[level]
        return {
            "check_id": check_id,
            "level": level,
            "status": status,
            "claim": "one bounded claim",
            "checker": {"name": "test-checker", "version": "1", "independence": independence},
            "evidence_refs": ["e1"] if status in ("PASS", "FAIL") else [],
            "scope": "this fixture only",
            "reason": "not available" if status not in ("PASS", "FAIL") else "",
            "valid_until": None,
        }

    def test_malformed_checks_report_field_errors_in_both_cli_formats(self):
        self.checks["checks"] = [None, dict(self._check(), check_id=[], level={},
                                            status=[], evidence_refs=[{}])]
        self._write_checks()
        for flags in ([], ["--json"]):
            run = subprocess.run([sys.executable, "-m", "ovo_acceptance", "proof",
                                  str(self.root), *flags], cwd=ROOT, capture_output=True,
                                 text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn("INVALID", run.stdout)
            self.assertIn("checks[1].level", run.stdout)
            self.assertEqual(run.stderr, "")

    def test_replay_summary_must_agree_with_manifest(self):
        manifest = self.root / "replay" / "manifest.json"
        data = json.loads(manifest.read_text())
        data.update(status="UNAVAILABLE", missing=["original inputs"])
        manifest.write_text(json.dumps(data))
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("REPLAY_STATUS_MISMATCH", self._codes(result))
        self.assertIn("REPLAY_GAP_MISMATCH", self._codes(result))

    def test_available_replay_cannot_have_missing_inputs(self):
        for filename in ("replay/manifest.json", "proof.json"):
            path = self.root / filename
            data = json.loads(path.read_text())
            section = data["replay"] if filename == "proof.json" else data
            section["missing"] = ["original inputs"]
            path.write_text(json.dumps(data))
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("REPLAY_INPUT_MISSING", self._codes(result))

    def test_empty_acceptance_bundle_is_invalid(self):
        (self.root / "bundle.json").write_text("{}", encoding="utf-8")
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("MISSING_BUNDLE", self._codes(result))

    def _write_trace(self):
        with (self.root / "trace.jsonl").open("w", encoding="utf-8") as handle:
            for step in self.bundle["execution_trace"]["steps"]:
                handle.write(json.dumps(step) + "\n")

    def _write_checks(self):
        (self.root / "checks.json").write_text(
            json.dumps(self.checks), encoding="utf-8")

    def _codes(self, result):
        return [item["code"] for item in result["errors"]]

    def test_valid_bundle_passes_without_collapsing_levels(self):
        self.checks["checks"] = [
            self._check("c0", "P0"), self._check("c1", "P1"),
            self._check("c2", "P2"), self._check("c3", "P3"),
            self._check("c4", "P4"),
        ]
        self._write_checks()
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual([], result["errors"])
        self.assertEqual("PASS", result["status"])
        self.assertEqual("PASS", result["contract_validation"]["status"])
        self.assertEqual("PASS", result["business_verdict"]["status"])
        self.assertEqual("EXPLICIT", result["time_semantics"]["status"])
        self.assertNotIn("proof_level", result)
        self.assertEqual({level: 1 for level in proof.LEVELS}, result["counts_by_level"])

    def test_business_failure_has_a_valid_contract_but_not_business_pass(self):
        self.checks["checks"] = [self._check(status="FAIL")]
        self._write_checks()
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual("PASS", result["contract_validation"]["status"])
        self.assertEqual("FAIL", result["business_verdict"]["status"])
        self.assertEqual([], result["errors"])
        self.assertFalse(result["ok"])

    def test_naive_time_is_indeterminate_not_business_pass(self):
        self.bundle["execution_trace"]["started_at"] = "2026-11-22T01:00:00"
        self.bundle["execution_trace"]["steps"][0]["started_at"] = "2026-11-22T01:00:00"
        (self.root / "bundle.json").write_text(json.dumps(self.bundle), encoding="utf-8")
        self._write_trace()
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual("PASS", result["contract_validation"]["status"])
        self.assertEqual("INDETERMINATE", result["business_verdict"]["status"])
        self.assertEqual("UNCERTAIN", result["time_semantics"]["status"])
        self.assertEqual("UTC", result["time_semantics"]["timezone_assumed"])
        self.assertTrue(result["time_semantics"]["paths"])
        self.assertEqual([], result["errors"])
        self.assertFalse(result["ok"])

    def test_unchecked_is_blocked_not_pass_or_fail(self):
        self.checks["checks"] = [self._check(status="UNCHECKED")]
        self._write_checks()
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual("BLOCKED", result["status"])
        self.assertFalse(result["ok"])
        self.assertEqual("not available", result["checks"][0]["reason"])

    def test_indeterminate_is_distinct_from_failure(self):
        self.checks["checks"] = [self._check(status="INDETERMINATE")]
        self._write_checks()
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("INDETERMINATE", result["checks"][0]["status"])
        self.assertNotEqual("FAIL", result["status"])

    def test_expired_is_not_current_pass(self):
        self.checks["checks"] = [self._check(status="EXPIRED")]
        self._write_checks()
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual("EXPIRED", result["status"])
        self.assertFalse(result["ok"])

    def test_independent_levels_reject_executor_self_attestation(self):
        self.checks["checks"] = [self._check(level="P3")]
        self.checks["checks"][0]["checker"]["independence"] = proof.EXECUTOR_OBSERVED
        self._write_checks()
        result = proof.validate_proof_bundle(self.root)
        self.assertIn("INDEPENDENCE_REQUIRED", self._codes(result))
        self.assertEqual("INVALID", result["status"])

    def test_pass_requires_registered_evidence(self):
        self.checks["checks"][0]["evidence_refs"] = []
        self._write_checks()
        result = proof.validate_proof_bundle(self.root)
        self.assertIn("PASS_WITHOUT_EVIDENCE", self._codes(result))

    def test_artifact_hash_is_recomputed(self):
        (self.root / "artifacts" / "brief.md").write_text("tampered\n", encoding="utf-8")
        result = proof.validate_proof_bundle(self.root)
        self.assertIn("ARTIFACT_HASH_MISMATCH", self._codes(result))

    def test_artifact_path_cannot_escape_bundle(self):
        doc = json.loads((self.root / "proof.json").read_text(encoding="utf-8"))
        doc["artifacts"][0]["path"] = "../outside.md"
        (self.root / "proof.json").write_text(json.dumps(doc), encoding="utf-8")
        result = proof.validate_proof_bundle(self.root)
        self.assertIn("UNSAFE_PATH", self._codes(result))

    def test_contract_and_trace_must_match_acceptance_bundle(self):
        contract = copy.deepcopy(self.bundle["task_contract"])
        contract["goal"] = "changed"
        (self.root / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
        self.bundle["execution_trace"]["steps"][0]["status"] = "failed"
        self._write_trace()
        result = proof.validate_proof_bundle(self.root)
        self.assertIn("CONTRACT_PROJECTION_MISMATCH", self._codes(result))
        self.assertIn("TRACE_PROJECTION_MISMATCH", self._codes(result))

    def test_blocked_acceptance_bundle_cannot_become_proof_pass(self):
        bundle = json.loads((self.root / "bundle.json").read_text(encoding="utf-8"))
        acceptance = bundle["acceptances"][0]
        acceptance["verdict"] = "UNPROVEN"
        acceptance["evidence_refs"] = []
        acceptance["notes"] = "missing external evidence"
        (self.root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
        result = proof.validate_proof_bundle(self.root)
        self.assertEqual("BLOCKED", result["status"])
        self.assertFalse(result["ok"])
        self.assertEqual("BLOCKED", result["acceptance_verdict"])

    def test_cli_returns_one_for_unproven_proof(self):
        self.checks["checks"] = [self._check(status="UNCHECKED")]
        self._write_checks()
        run = subprocess.run(
            [sys.executable, "-m", "ovo_acceptance", "proof", str(self.root), "--json"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(1, run.returncode, run.stdout + run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual("BLOCKED", payload["status"])
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
