from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ovo_acceptance import roadmap_coverage

ROOT = Path(__file__).resolve().parents[1]


def item(item_id="A1-01", implementation="local", acceptance="synthetic_passed"):
    return {
        "item_id": item_id, "title": "Source discovery", "priority": "P0",
        "implementation_status": implementation, "acceptance_status": acceptance,
        "evidence_refs": ["code:source-discovery"], "test_refs": ["tests/test_sources.py"],
        "case_refs": ["A-L3-SYNTH-01"],
        "scope_decision": {"status": "not_needed", "rationale": "In scope"},
        "unresolved": ["Real external acceptance"] if acceptance != "accepted_external" else [],
    }


class RoadmapCoverageTest(unittest.TestCase):
    def test_summarizes_work_items_without_conflating_acceptance(self):
        result = roadmap_coverage.summarize({
            "schema": "ovo.roadmap-work-items/1", "roadmap_id": "r1", "source_ref": "fixture",
            "modules": [{"module_id": "A1", "product": "askovo", "title": "Data",
                         "items": [item(), item("A1-02", "unknown", "not_run")]}],
        })
        self.assertEqual(2, result["coverage"]["total"])
        self.assertEqual(1, result["coverage"]["implementation"]["local"])
        self.assertEqual(1, result["coverage"]["implementation"]["unknown"])
        self.assertEqual(2, result["coverage"]["not_accepted_external"])
        self.assertEqual(2, result["coverage"]["by_product"]["askovo"])

    def test_external_only_or_not_implemented_needs_scope_decision(self):
        row = item(implementation="external_only")
        row["scope_decision"] = {"status": "pending", "rationale": "Needs owner scope"}
        result = roadmap_coverage.summarize({
            "schema": "ovo.roadmap-work-items/1", "roadmap_id": "r1", "source_ref": "fixture",
            "modules": [{"module_id": "A1", "product": "askovo", "title": "Data", "items": [row]}],
        })
        self.assertEqual(1, result["coverage"]["pending_scope_decisions"])
        row["scope_decision"] = {"status": "pending", "rationale": ""}
        with self.assertRaisesRegex(ValueError, "rationale"):
            roadmap_coverage.summarize({
                "schema": "ovo.roadmap-work-items/1", "roadmap_id": "r1", "source_ref": "fixture",
                "modules": [{"module_id": "A1", "product": "askovo", "title": "Data", "items": [row]}],
            })

    def test_duplicate_and_module_product_mismatch_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            roadmap_coverage.summarize({
                "schema": "ovo.roadmap-work-items/1", "roadmap_id": "r1", "source_ref": "fixture",
                "modules": [{"module_id": "A1", "product": "askovo", "title": "Data",
                             "items": [item(), item()]}],
            })
        row = item("G1-01")
        with self.assertRaisesRegex(ValueError, "product"):
            roadmap_coverage.summarize({
                "schema": "ovo.roadmap-work-items/1", "roadmap_id": "r1", "source_ref": "fixture",
                "modules": [{"module_id": "G1", "product": "askovo", "title": "Context", "items": [row]}],
            })

    def test_cli_outputs_roadmap_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roadmap.json"
            path.write_text(json.dumps({
                "schema": "ovo.roadmap-work-items/1", "roadmap_id": "r1", "source_ref": "fixture",
                "modules": [{"module_id": "A1", "product": "askovo", "title": "Data", "items": [item()]}],
            }), encoding="utf-8")
            result = subprocess.run([
                sys.executable, "-m", "ovo_acceptance", "roadmap-coverage", str(path), "--json",
            ], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual(1, json.loads(result.stdout)["coverage"]["total"])


if __name__ == "__main__":
    unittest.main()
