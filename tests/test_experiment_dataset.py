from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ovo_acceptance import experiment_dataset

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/valid-experiment-contract.json"


def experiment():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class ExperimentDatasetTest(unittest.TestCase):
    def test_build_validates_and_inventories_without_pooling_metrics(self):
        document = experiment_dataset.build([experiment()], dataset_id="dataset-1")
        self.assertEqual("ovo.experiment-dataset/1", document["schema"])
        self.assertEqual("local_only", document["classification"])
        self.assertEqual("not_authorized", document["public_release"])
        self.assertEqual(1, document["summary"]["experiments"])
        self.assertEqual(2, document["summary"]["eligible_observations"])
        self.assertEqual({"askovo": 1}, document["summary"]["products"])
        self.assertEqual("descriptive_inventory_only", document["analysis"])
        self.assertNotIn("pooled_success_rate", document["summary"])
        self.assertTrue(document["dataset_sha256"].startswith("sha256:"))

    def test_invalid_experiment_is_rejected(self):
        document = experiment()
        document["design_sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "DESIGN_FINGERPRINT_MISMATCH"):
            experiment_dataset.build([document], dataset_id="dataset-1")

    def test_duplicate_origin_experiment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            experiment_dataset.build([experiment(), experiment()], dataset_id="dataset-1")

    def test_cli_writes_new_local_dataset_and_refuses_overwrite(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "dataset"
        command = [sys.executable, "-m", "ovo_acceptance", "experiment-dataset",
                   "--dataset-id", "dataset-cli", "--out", str(out), str(EXAMPLE)]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
        self.assertEqual("dataset-cli", payload["dataset_id"])
        duplicate = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(0, duplicate.returncode)


if __name__ == "__main__":
    unittest.main()
