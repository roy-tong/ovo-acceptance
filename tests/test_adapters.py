from __future__ import annotations

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

from ovo_acceptance import adapters, model, proof  # noqa: E402
from test_acceptance import CONTRACT_ID, T, _valid_bundle  # noqa: E402


def build_proof_bundle(root: Path) -> Path:
    bundle = _valid_bundle()
    (root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (root / "contract.json").write_text(
        json.dumps(bundle["task_contract"]), encoding="utf-8")
    (root / "trace.jsonl").write_text(
        "".join(json.dumps(step) + "\n"
                for step in bundle["execution_trace"]["steps"]),
        encoding="utf-8")
    artifact = root / "artifacts" / "brief.md"
    artifact.parent.mkdir()
    artifact.write_text("decision brief\n", encoding="utf-8")
    artifact_hash = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
    (root / "proof.json").write_text(json.dumps({
        "schema": proof.PROOF_SCHEMA,
        "proof_id": "proof-adapter-001",
        "contract_id": CONTRACT_ID,
        "product": "askovo",
        "generated_at": T,
        "environment": {"product_version": "2.22.1", "runtime": "Python 3.9"},
        "artifacts": [{
            "artifact_id": "brief",
            "path": "artifacts/brief.md",
            "sha256": artifact_hash,
            "classification": "synthetic",
        }],
        "replay": {
            "manifest": "replay/manifest.json",
            "status": "AVAILABLE",
            "missing": [],
        },
        "limitations": ["synthetic example"],
    }), encoding="utf-8")
    replay = root / "replay" / "manifest.json"
    replay.parent.mkdir()
    replay.write_text(json.dumps({
        "schema": proof.REPLAY_SCHEMA,
        "contract_id": CONTRACT_ID,
        "status": "AVAILABLE",
        "commands": [{"name": "validate", "argv": ["python3", "-m",
                                                   "ovo_acceptance", "bundle",
                                                   "bundle.json"]}],
        "inputs": [{"ref": "bundle.json", "sha256": "sha256:" + "b" * 64}],
        "missing": [],
    }), encoding="utf-8")
    (root / "checks.json").write_text(json.dumps({
        "schema": proof.CHECKS_SCHEMA,
        "contract_id": CONTRACT_ID,
        "checks": [{
            "check_id": "c1",
            "level": "P1",
            "status": "PASS",
            "claim": "the brief exists and is readable",
            "checker": {
                "name": "test",
                "version": "1",
                "independence": proof.EXECUTOR_OBSERVED,
            },
            "evidence_refs": ["e1"],
            "scope": "artifact",
            "reason": "",
        }],
    }), encoding="utf-8")
    return root


class AdapterTests(unittest.TestCase):
    def test_receipt_from_proof_bundle_is_observed_not_business(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundle"
            root.mkdir()
            build_proof_bundle(root)
            for name in ("bundle.json", "contract.json", "trace.jsonl",
                         "proof.json", "checks.json"):
                self.assertTrue((root / name).is_file(), name)
            receipt = adapters.receipt_from_proof_bundle(root, reviewed_by="demo")
        self.assertEqual([], model.validate_document(receipt))
        self.assertEqual("askovo", receipt["origin_product"])
        self.assertEqual(CONTRACT_ID, receipt["task_id"])
        self.assertEqual("observed", receipt["verification_state"])
        self.assertEqual("not_claimed", receipt["causality"])
        self.assertTrue(receipt["source_hash"].startswith("sha256:"))
        self.assertEqual("demo", receipt["human_review"]["reviewed_by"])

    def test_every_product_has_a_valid_capability(self) -> None:
        for product, side_effect in (("askovo", "read_external"),
                                     ("growovo", "write_external"),
                                     ("verovo", "none")):
            descriptor = adapters.capability_descriptor(product)
            self.assertEqual([], model.validate_document(descriptor))
            self.assertEqual(side_effect, descriptor["side_effect_level"])

    def test_cli_writes_receipt_and_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundle"
            root.mkdir()
            build_proof_bundle(root)
            receipt_out = Path(directory) / "receipt.json"
            capability_out = Path(directory) / "capability.json"
            receipt = subprocess.run(
                [sys.executable, "-m", "ovo_acceptance", "adapter",
                 "--proof", str(root), "--out", str(receipt_out), "--by", "demo"],
                cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(0, receipt.returncode, receipt.stderr + receipt.stdout)
            capability = subprocess.run(
                [sys.executable, "-m", "ovo_acceptance", "adapter",
                 "--product", "growovo", "--out", str(capability_out)],
                cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(0, capability.returncode,
                             capability.stderr + capability.stdout)
            self.assertEqual([], model.validate_document(json.loads(
                receipt_out.read_text(encoding="utf-8"))))
            self.assertEqual([], model.validate_document(json.loads(
                capability_out.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    unittest.main()
