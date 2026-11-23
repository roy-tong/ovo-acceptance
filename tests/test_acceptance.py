"""Contract tests for the OVO shared acceptance layer.

Each test breaks exactly one rule of an otherwise valid bundle, so the error
code can be asserted without guessing which other rule fired first.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ovo_acceptance import model  # noqa: E402

HASH = "sha256:" + "a" * 64
T = "2026-11-22T10:00:00+08:00"
CONTRACT_ID = "family-2026-11-22-001"
TRACE_ID = "trace-2026-11-22-001"


def _codes(errors):
    return [item["code"] for item in errors]


def _valid_ledger():
    return {
        "schema": model.LEDGER_SCHEMA,
        "ledger_id": "ledger-001",
        "contract_id": CONTRACT_ID,
        "entries": [
            {
                "evidence_id": "e1",
                "kind": "source_document",
                "source_ref": "store/obs-001.json",
                "source_hash": HASH,
                "observed_at": T,
                "collected_by": "roy",
                "trust": "observed",
            }
        ],
    }


def _observation_entry():
    return {
        "evidence_id": "e2",
        "kind": "observation",
        "source_ref": "store/obs-002.json",
        "source_hash": HASH,
        "observed_at": T,
        "collected_by": "roy",
        "trust": "observed",
        "context": {
            "product_version": "2.20.3",
            "account_permission": "admin",
            "platform": "web",
            "region": "CN",
        },
        "generalization": "single_case",
        "repeat_count": 1,
    }


def _valid_bundle():
    return {
        "schema": model.BUNDLE_SCHEMA,
        "task_contract": {
            "schema": model.TASK_SCHEMA,
            "contract_id": CONTRACT_ID,
            "version": "1",
            "created_at": T,
            "owner": "roy",
            "product": "family",
            "goal": "verify one deliverable",
            "inputs": [{"ref": "store/obs-001.json", "kind": "observation"}],
            "deliverables": [
                {
                    "id": "d1",
                    "description": "one observation record",
                    "acceptance_criteria": ["证据可追溯到账本"],
                }
            ],
            "approved_by": "roy",
        },
        "execution_trace": {
            "schema": model.TRACE_SCHEMA,
            "trace_id": TRACE_ID,
            "contract_id": CONTRACT_ID,
            "started_at": T,
            "finished_at": "2026-11-22T10:05:00+08:00",
            "actor": "test",
            "steps": [
                {
                    "step_id": "s1",
                    "action": "record",
                    "started_at": T,
                    "ended_at": "2026-11-22T10:01:00+08:00",
                    "status": "ok",
                }
            ],
        },
        "evidence_ledger": _valid_ledger(),
        "acceptances": [
            {
                "schema": model.ACCEPTANCE_SCHEMA,
                "acceptance_id": "acc-001",
                "contract_id": CONTRACT_ID,
                "trace_id": TRACE_ID,
                "deliverable_id": "d1",
                "criterion": "证据可追溯到账本",
                "verdict": "PASS",
                "evidence_refs": ["e1"],
                "checked_by": "roy",
                "checked_at": T,
            }
        ],
        "escalations": [],
    }


def _unproven_bundle(decision="accept_with_gap", trigger="unproven_evidence"):
    bundle = _valid_bundle()
    record = bundle["acceptances"][0]
    record["verdict"] = "UNPROVEN"
    record["evidence_refs"] = []
    record["notes"] = "只有单次观察，不能证明普遍行为"
    bundle["escalations"] = [
        {
            "schema": model.ESCALATION_SCHEMA,
            "escalation_id": "esc-001",
            "contract_id": CONTRACT_ID,
            "deliverable_id": "d1",
            "criterion": record["criterion"],
            "trigger": trigger,
            "raised_at": T,
            "raised_by": "roy",
            "owner": "roy",
            "decision": decision,
            "decision_by": "roy",
            "decided_at": T,
            "next_action": "补三个不同平台的观察",
        }
    ]
    return bundle


class BundleValidationTest(unittest.TestCase):
    def test_example_bundle_is_accepted(self):
        bundle = model.load_json(ROOT / "examples" / "valid-bundle.json")
        result = model.validate_bundle(bundle)
        self.assertEqual([], result["errors"])
        self.assertEqual("PASS", result["verdict"])
        self.assertTrue(result["ok"])

    def test_valid_bundle_passes(self):
        result = model.validate_bundle(_valid_bundle())
        self.assertEqual([], result["errors"])
        self.assertEqual("PASS", result["verdict"])
        self.assertTrue(result["ok"])

    def test_mixed_naive_and_aware_instants_are_compared_without_crashing(self):
        bundle = _valid_bundle()
        trace = bundle["execution_trace"]
        trace["started_at"] = "2026-11-22T01:00:00"
        trace["steps"][0]["started_at"] = "2026-11-22T01:00:00"
        result = model.validate_bundle(bundle)
        self.assertEqual([], result["errors"])
        self.assertEqual("PASS", result["verdict"])

    def test_pass_without_evidence_is_rejected(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["evidence_refs"] = []
        result = model.validate_bundle(bundle)
        self.assertIn("PASS_WITHOUT_EVIDENCE", _codes(result["errors"]))
        self.assertFalse(result["ok"])

    def test_pass_citing_unknown_evidence_is_rejected(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["evidence_refs"] = ["e404"]
        result = model.validate_bundle(bundle)
        self.assertIn("UNKNOWN_EVIDENCE", _codes(result["errors"]))

    def test_deliverable_without_acceptance_is_blocked(self):
        bundle = _valid_bundle()
        bundle["acceptances"] = []
        result = model.validate_bundle(bundle)
        self.assertIn("NO_ACCEPTANCE", _codes(result["errors"]))
        self.assertEqual("BLOCKED", result["verdict"])

    def test_fail_without_escalation_is_reported(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["verdict"] = "FAIL"
        bundle["acceptances"][0]["evidence_refs"] = []
        bundle["acceptances"][0]["notes"] = "criterion not met"
        result = model.validate_bundle(bundle)
        self.assertIn("FAIL_WITHOUT_ESCALATION", _codes(result["errors"]))
        self.assertEqual("FAIL", result["verdict"])

    def test_unproven_without_escalation_is_blocked(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["verdict"] = "UNPROVEN"
        bundle["acceptances"][0]["evidence_refs"] = []
        result = model.validate_bundle(bundle)
        self.assertEqual([], result["errors"])
        self.assertEqual("BLOCKED", result["verdict"])
        self.assertFalse(result["ok"])

    def test_unproven_accepted_with_gap_is_pass_with_gap(self):
        result = model.validate_bundle(_unproven_bundle())
        self.assertEqual([], result["errors"])
        self.assertEqual("PASS_WITH_GAP", result["verdict"])
        self.assertTrue(result["ok"])

    def test_unproven_with_failed_criterion_trigger_is_invalid(self):
        result = model.validate_bundle(
            _unproven_bundle(trigger="failed_criterion"))
        self.assertIn("ESCALATION_TRIGGER", _codes(result["errors"]))

    def test_trace_from_another_contract_is_rejected(self):
        bundle = _valid_bundle()
        bundle["execution_trace"]["contract_id"] = "other-contract"
        result = model.validate_bundle(bundle)
        self.assertIn("CONTRACT_MISMATCH", _codes(result["errors"]))

    def test_dangling_retry_is_rejected(self):
        bundle = _valid_bundle()
        bundle["execution_trace"]["steps"].append({
            "step_id": "s2",
            "action": "record",
            "started_at": T,
            "ended_at": "2026-11-22T10:02:00+08:00",
            "status": "ok",
            "retry_of": "s404",
        })
        result = model.validate_bundle(bundle)
        self.assertIn("DANGLING_LINK", _codes(result["errors"]))

    def test_vendor_step_keeps_external_id(self):
        bundle = _valid_bundle()
        bundle["execution_trace"]["steps"][0]["vendor"] = "openai"
        result = model.validate_bundle(bundle)
        self.assertIn("VENDOR_ID_MISSING", _codes(result["errors"]))

    def test_criterion_must_quote_the_contract(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["criterion"] = "看起来不错"
        result = model.validate_bundle(bundle)
        self.assertIn("CRITERION_MISMATCH", _codes(result["errors"]))

    def test_unknown_extra_field_is_rejected(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["confidence"] = 0.9
        result = model.validate_bundle(bundle)
        self.assertIn("UNKNOWN_FIELD", _codes(result["errors"]))


class ObservationValidationTest(unittest.TestCase):
    def _ledger_errors(self, entry):
        ledger = _valid_ledger()
        ledger["entries"].append(entry)
        return model.validate_evidence_ledger(ledger)

    def test_valid_observation_entry(self):
        self.assertEqual([], self._ledger_errors(_observation_entry()))

    def test_observation_needs_full_context(self):
        entry = _observation_entry()
        del entry["context"]["platform"]
        errors = self._ledger_errors(entry)
        self.assertIn("OBSERVATION_CONTEXT", _codes(errors))

    def test_observation_cannot_be_universal(self):
        entry = _observation_entry()
        entry["generalization"] = "universal"
        errors = self._ledger_errors(entry)
        self.assertIn("OBSERVATION_GENERALIZATION", _codes(errors))

    def test_single_case_is_exactly_one_run(self):
        entry = _observation_entry()
        entry["repeat_count"] = 3
        errors = self._ledger_errors(entry)
        self.assertIn("OBSERVATION_REPEAT", _codes(errors))

    def test_repeated_needs_two_runs(self):
        entry = _observation_entry()
        entry["generalization"] = "repeated"
        entry["repeat_count"] = 1
        errors = self._ledger_errors(entry)
        self.assertIn("OBSERVATION_REPEAT", _codes(errors))

    def test_multi_context_needs_two_distinct_contexts(self):
        entry = _observation_entry()
        entry["generalization"] = "multi_context"
        entry["repeat_count"] = 2
        entry["contexts"] = [copy.deepcopy(entry["context"]),
                             copy.deepcopy(entry["context"])]
        errors = self._ledger_errors(entry)
        self.assertIn("OBSERVATION_CONTEXTS", _codes(errors))

    def test_multi_context_with_two_contexts_passes(self):
        entry = _observation_entry()
        entry["generalization"] = "multi_context"
        entry["repeat_count"] = 2
        second = copy.deepcopy(entry["context"])
        second["platform"] = "ios"
        entry["contexts"] = [copy.deepcopy(entry["context"]), second]
        self.assertEqual([], self._ledger_errors(entry))

    def test_observation_must_be_observed_trust(self):
        entry = _observation_entry()
        entry["trust"] = "reported"
        errors = self._ledger_errors(entry)
        self.assertIn("OBSERVATION_TRUST", _codes(errors))

    def test_bad_hash_format_is_rejected(self):
        entry = _observation_entry()
        entry["source_hash"] = "abc"
        errors = self._ledger_errors(entry)
        self.assertIn("HASH_FORMAT", _codes(errors))


class CliTest(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "ovo_acceptance", *args],
            cwd=str(ROOT), capture_output=True, text=True)

    def test_validate_valid_document_exits_zero(self):
        bundle = _valid_bundle()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            path.write_text(json.dumps(bundle["evidence_ledger"]),
                            encoding="utf-8")
            run = self._run("validate", str(path))
        self.assertEqual(0, run.returncode, run.stderr + run.stdout)
        self.assertIn("校验通过", run.stdout)

    def test_validate_invalid_document_exits_one(self):
        ledger = _valid_ledger()
        ledger["entries"][0]["trust"] = "hearsay"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            path.write_text(json.dumps(ledger), encoding="utf-8")
            run = self._run("validate", str(path))
        self.assertEqual(1, run.returncode)
        self.assertIn("ENUM", run.stdout)

    def test_missing_file_exits_two(self):
        run = self._run("validate", str(ROOT / "examples" / "nope.json"))
        self.assertEqual(2, run.returncode)
        self.assertIn("ERROR", run.stderr)

    def test_bundle_dir_and_file(self):
        run = self._run("bundle", str(ROOT / "examples" / "valid-bundle.json"))
        self.assertEqual(0, run.returncode, run.stdout)
        self.assertIn("PASS", run.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bundle.json").write_text(
                json.dumps(_valid_bundle()), encoding="utf-8")
            run = self._run("bundle", tmp)
        self.assertEqual(0, run.returncode, run.stdout)

    def test_bundle_failure_exits_one(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["evidence_refs"] = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            run = self._run("bundle", tmp, "--json")
        self.assertEqual(1, run.returncode)
        payload = json.loads(run.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("PASS_WITHOUT_EVIDENCE",
                      [item["code"] for item in payload["errors"]])


if __name__ == "__main__":
    unittest.main()
