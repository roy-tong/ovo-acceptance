from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from ovo_acceptance import casebook

ROOT = Path(__file__).resolve().parents[1]


class CaseEntryTests(unittest.TestCase):
    def test_shared_case_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "cases.jsonl"
            registry.write_text(json.dumps({"case_id": "DEMO-CASE", "title": "Demo", "product": "Askovo", "status": "delivered"}) + "\n", encoding="utf-8")
            env = os.environ.copy()
            env["OVO_CASE_REGISTRY"] = str(registry)
            result = subprocess.run([sys.executable, "-m", "ovo_acceptance", "case", "list"], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("DEMO-CASE", result.stdout)

    def test_validate_uses_registry_workspace(self) -> None:
        result = subprocess.run([sys.executable, "-m", "ovo_acceptance", "case", "validate"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)

    def test_custom_registry_uses_current_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artifact.txt").write_text("demo", encoding="utf-8")
            case = {
                "case_id": "DEMO-CASE", "product": "Askovo", "title": "Demo", "status": "delivered",
                "time_window": "2026", "goal": "demo", "source_sessions": [{"host": "zcode", "id": "sess_demo"}],
                "artifacts": [{"path": "artifact.txt"}],
                "outcome": {"artifact": "demo", "execution": "demo", "business": "unknown", "adoption": "unknown"},
                "replay": {"mode": "artifact_audit", "expect_contains": {}}, "sensitivity": "public",
            }
            registry = root / "cases.jsonl"
            registry.write_text(json.dumps(case) + "\n", encoding="utf-8")
            env = os.environ.copy()
            env["OVO_CASE_REGISTRY"] = str(registry)
            env["PYTHONPATH"] = str(ROOT)
            result = subprocess.run([sys.executable, "-m", "ovo_acceptance", "case", "validate"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
    def test_golden_script_runs_in_isolated_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "replay.py"
            (root / "fixtures").mkdir()
            (root / "fixtures/input.txt").write_text("frozen fixture", encoding="utf-8")
            script.write_text(
                "import argparse,json\n"
                "from pathlib import Path\n"
                "p=argparse.ArgumentParser(); p.add_argument('--inputs',required=True); p.add_argument('--out',required=True); a=p.parse_args()\n"
                "assert (Path(a.inputs)/'input.txt').read_text() == 'frozen fixture'\n"
                "Path(a.out).mkdir(parents=True)\n"
                "result={'status':'passed','verification_type':'task_rerun','external_writes':0}\n"
                "(Path(a.out)/'result.json').write_text(json.dumps(result))\n"
                "print(json.dumps(result))\n", encoding="utf-8")
            case = {"case_id": "DEMO-GOLDEN", "replay": {
                "mode": "golden_script", "script": "replay.py", "argv": ["--inputs", "fixtures", "--out", "{run_dir}/workspace"]}}
            result = casebook.replay_case([case], "DEMO-GOLDEN", root=root, run_root=root / "runs")
            self.assertEqual("passed", result["status"])
            self.assertEqual("task_rerun", result["verification_type"])
            self.assertTrue((root / "runs/DEMO-GOLDEN/workspace/result.json").is_file())
            self.assertTrue((root / "runs/DEMO-GOLDEN/command-1.log").is_file())


if __name__ == "__main__":
    unittest.main()
