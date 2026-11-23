from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ovo_acceptance import model  # noqa: E402
from ovo_acceptance import publish  # noqa: E402
from test_acceptance import _unproven_bundle, _valid_bundle  # noqa: E402


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "public"

    def tearDown(self):
        self.tmp.cleanup()

    def test_confidential_bundle_is_refused(self):
        with self.assertRaises(publish.PublicationError):
            publish.publish_bundle(
                _valid_bundle(), self.out,
                classification="confidential", approved_by="roy")

    def test_publication_requires_named_reviewer(self):
        with self.assertRaises(publish.PublicationError):
            publish.publish_bundle(
                _valid_bundle(), self.out,
                classification="synthetic", approved_by="")

    def test_invalid_bundle_is_not_published(self):
        bundle = _valid_bundle()
        bundle["acceptances"][0]["evidence_refs"] = []
        with self.assertRaises(publish.PublicationError):
            publish.publish_bundle(
                bundle, self.out, classification="synthetic", approved_by="roy")

    def test_synthetic_publication_is_replayable_and_escaped(self):
        bundle = _valid_bundle()
        bundle["task_contract"]["goal"] = "<script>alert(1)</script>"
        result = publish.publish_bundle(
            bundle, self.out, classification="synthetic",
            approved_by="<script>alert('publisher')</script>")
        self.assertEqual("PASS", result["verdict"])
        self.assertEqual("ovo.task-template/1", result["template"]["schema"])
        self.assertEqual("PASS", model.validate_bundle(result["bundle"])["verdict"])
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("alert(1)", html)
        self.assertNotIn("store/obs-001.json", json.dumps(result["bundle"]))
        self.assertEqual("PASS", model.validate_bundle(
            json.loads((self.out / "bundle.json").read_text(encoding="utf-8")))["verdict"])

    def test_public_projection_redacts_all_free_text_and_nested_sources(self):
        bundle = _unproven_bundle()
        task = bundle["task_contract"]
        deliverable = task["deliverables"][0]
        step = bundle["execution_trace"]["steps"][0]
        evidence = bundle["evidence_ledger"]["entries"][0]
        acceptance = bundle["acceptances"][0]
        escalation = bundle["escalations"][0]
        task.update({
            "owner": "PRIVATE-task-owner-001", "goal": "PRIVATE-goal-002",
            "approved_by": "PRIVATE-contract-approver-003",
        })
        task["inputs"][0]["ref"] = "PRIVATE/input-004/customer.json"
        task["inputs"][0]["notes"] = "PRIVATE-input-note-005"
        deliverable["description"] = "PRIVATE-deliverable-006"
        deliverable["acceptance_criteria"] = ["PRIVATE-criterion-007"]
        deliverable["out_of_scope"] = ["PRIVATE-scope-008"]
        bundle["execution_trace"]["actor"] = "PRIVATE-actor-009"
        step.update({
            "action": "PRIVATE-action-010", "tool": "PRIVATE-tool-011",
            "input_ref": "PRIVATE/input-012.json", "output_ref": "PRIVATE/output-013.json",
            "vendor": "PRIVATE-vendor-014", "external_id": "PRIVATE-external-015",
        })
        evidence.update({
            "source_ref": "PRIVATE/evidence-016.json", "collected_by": "PRIVATE-collector-017",
            "notes": "PRIVATE-evidence-note-018",
            "context": {
                "product_version": "PRIVATE-version-019",
                "account_permission": "PRIVATE-permission-020",
                "platform": "PRIVATE-platform-021", "region": "PRIVATE-region-022",
            },
        })
        acceptance.update({
            "criterion": "PRIVATE-criterion-007", "checked_by": "PRIVATE-checker-023",
            "notes": "PRIVATE-acceptance-note-024",
        })
        escalation.update({
            "criterion": "PRIVATE-criterion-007", "raised_by": "PRIVATE-raiser-025",
            "owner": "PRIVATE-escalation-owner-026", "decision_by": "PRIVATE-decider-027",
            "next_action": "PRIVATE-next-action-028", "notes": "PRIVATE-escalation-note-029",
        })
        result = publish.publish_bundle(
            bundle, self.out, classification="public-redacted", approved_by="roy")

        self.assertEqual("PASS_WITH_GAP", result["verdict"])
        self.assertEqual([], model.validate_bundle(result["bundle"])["errors"])
        for name in ("bundle.json", "template.json", "index.html", "share.json"):
            public_text = (self.out / name).read_text(encoding="utf-8")
            for index in range(1, 30):
                self.assertNotIn("PRIVATE-", public_text, "%s leaked sentinel %d" % (name, index))
        self.assertEqual("PRIVATE-goal-002", bundle["task_contract"]["goal"])
        self.assertEqual("roy", result["share"]["approved_by"])

    def test_cli_publishes_public_proof(self):
        source = self.root / "source.json"
        source.write_text(json.dumps(_valid_bundle()), encoding="utf-8")
        run = subprocess.run(
            [sys.executable, "-m", "ovo_acceptance", "publish", str(source),
             "--out", str(self.out), "--classification", "synthetic",
             "--by", "roy", "--json"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual("PASS", payload["verdict"])
        self.assertTrue((self.out / "template.json").is_file())
        self.assertTrue((self.out / "share.json").is_file())


if __name__ == "__main__":
    unittest.main()
