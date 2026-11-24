from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_installed_wheel_validates_cases_and_contracts_outside_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheelhouse = root / "wheelhouse"
            built = subprocess.run([
                sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                "--wheel-dir", str(wheelhouse), str(ROOT),
            ], cwd=root, text=True, capture_output=True)
            self.assertEqual(0, built.returncode, built.stderr + built.stdout)
            wheels = list(wheelhouse.glob("ovo_acceptance-*.whl"))
            self.assertEqual(1, len(wheels))
            venv.EnvBuilder(with_pip=True).create(root / "venv")
            python = root / "venv/bin/python"
            subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
                           cwd=root, text=True, capture_output=True, check=True)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "artifact.txt").write_text("real user task\n", encoding="utf-8")
            case = {
                "case_id": "INSTALLED-CASE", "product": "Askovo", "title": "Installed case",
                "status": "delivered", "time_window": "2026", "goal": "portable replay",
                "source_sessions": [{"host": "kimi-code", "id": "local-test"}],
                "artifacts": [{"path": "artifact.txt"}],
                "outcome": {"artifact": "present", "execution": "rerun", "business": "unknown", "adoption": "unknown"},
                "replay": {"mode": "artifact_audit", "expect_contains": {"artifact.txt": ["real user task"]}},
                "sensitivity": "private",
            }
            registry = workspace / "cases.jsonl"
            registry.write_text(json.dumps(case) + "\n", encoding="utf-8")
            env = {key: value for key, value in os.environ.items()
                   if key != "PYTHONPATH" and not key.startswith("OVO_")}
            env["OVO_CASE_REGISTRY"] = str(registry)
            executable = root / "venv/bin/ovo-acceptance"
            validated = subprocess.run([str(executable), "case", "validate"], cwd=workspace, env=env,
                                       text=True, capture_output=True)
            self.assertEqual(0, validated.returncode, validated.stderr + validated.stdout)
            replayed = subprocess.run([str(executable), "case", "replay", "INSTALLED-CASE",
                                       "--run-root", "runs"], cwd=workspace, env=env,
                                      text=True, capture_output=True)
            self.assertEqual(0, replayed.returncode, replayed.stderr + replayed.stdout)
            self.assertEqual("passed", json.loads(replayed.stdout)["status"])
            contract = subprocess.run([str(executable), "bundle", str(ROOT / "examples/valid-bundle.json")],
                                      cwd=workspace, env=env, text=True, capture_output=True)
            self.assertEqual(0, contract.returncode, contract.stderr + contract.stdout)


if __name__ == "__main__":
    unittest.main()
