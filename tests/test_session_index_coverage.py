from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ovo_acceptance import casebook


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class ProductPatternTests(unittest.TestCase):
    def test_verovo_is_tagged(self) -> None:
        self.assertIn("Verovo", casebook._products("Verovo 账期核验与 AgentMeasure 对账"))
        self.assertIn("Verovo", casebook._products("buyer-ledger close review"))

    def test_case_validator_accepts_verovo(self) -> None:
        case = {
            "case_id": "V-DEMO-01",
            "product": "Verovo",
            "title": "demo",
            "status": "delivered",
            "time_window": "2026-11",
            "goal": "demo",
            "source_sessions": [{"host": "zcode", "id": "sess_demo"}],
            "artifacts": [{"path": "artifact.txt"}],
            "outcome": {"artifact": "a", "execution": "e", "business": "b", "adoption": "d"},
            "replay": {"mode": "artifact_audit", "expect_contains": {}},
            "sensitivity": "public",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artifact.txt").write_text("demo", encoding="utf-8")
            errors = casebook.validate_cases([case], root=root, check_paths=True)
        self.assertEqual([], errors)


class KimiWorkCollectorTests(unittest.TestCase):
    def test_collects_titles_turns_and_products(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = "agent:main:main:conversation:abc"
            write_json(root / "conversation-titles.json", {key: "Verovo 账期核验"})
            write_json(root / "conversation-statuses.json", {key: "completed"})
            write_json(root / "conversation-projects.json",
                       {key: "/Users/demo/ovo family/Verovo"})
            write_json(root / "conversation-context-usage.json",
                       {key: {"updatedAt": "2026-11-24T10:00:00Z", "model": "demo"}})
            write_json(root / "segment-turn-metrics.json", {
                "x:" + key + ":seg1": {"finishStatus": "success"},
                "x:" + key + ":seg2": {"finishStatus": "interrupted"},
            })
            rows = list(casebook._kimi_work_sessions(root))
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("kimi-work", row["host"])
        self.assertEqual("abc", row["id"])
        self.assertEqual("Verovo 账期核验", row["title"])
        self.assertEqual(2, row["turns"])
        self.assertEqual(1, row["interrupted_turns"])
        self.assertIn("Verovo", row["candidate_products"])


class DshCollectorTests(unittest.TestCase):
    def test_reads_nested_zstd_session(self) -> None:
        import zstandard
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_dir = root / "workspace" / "sess-1"
            session_dir.mkdir(parents=True)
            lines = [
                {"type": "session", "id": "sess-1", "createdAt": 1794763200000,
                 "cwd": "/Users/demo/ovo family"},
                {"type": "session/title", "data": {"title": "Verovo 核验"}},
                {"type": "user/message",
                 "data": {"content": [{"type": "text", "text": "核对账期"}]}},
            ]
            payload = "\n".join(json.dumps(item, ensure_ascii=False) for item in lines) + "\n"
            with (session_dir / "session.v4.jsonl.zstd").open("wb") as handle:
                handle.write(zstandard.ZstdCompressor().compress(payload.encode("utf-8")))
            rows = list(casebook._dsh_sessions(root))
        self.assertEqual(1, len(rows))
        self.assertEqual("sess-1", rows[0]["id"])
        self.assertEqual("Verovo 核验", rows[0]["title"])
        self.assertEqual("Verovo", rows[0]["candidate_products"][0])
        self.assertIsNotNone(rows[0]["date"])

    def test_skips_unrelated_workspace(self) -> None:
        import zstandard
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_dir = root / "other" / "sess-2"
            session_dir.mkdir(parents=True)
            lines = [
                {"type": "session", "id": "sess-2", "createdAt": 1794763200000,
                 "cwd": "/Users/demo/unrelated-project"},
                {"type": "user/message",
                 "data": {"content": [{"type": "text", "text": "hello"}]}},
            ]
            payload = "\n".join(json.dumps(item) for item in lines) + "\n"
            with (session_dir / "session.v4.jsonl.zstd").open("wb") as handle:
                handle.write(zstandard.ZstdCompressor().compress(payload.encode("utf-8")))
            rows = list(casebook._dsh_sessions(root))
        self.assertEqual([], rows)


class IncidentEvidenceTests(unittest.TestCase):
    def test_external_url_is_not_a_missing_local_path(self) -> None:
        incident = {
            "incident_id": "I-DEMO",
            "case_id": "G-DEMO-01",
            "title": "demo",
            "status": "fixed",
            "symptom": "demo",
            "root_cause": "demo",
            "resolution": {"then": "t", "current": "c", "unresolved": "u"},
            "source_sessions": [{"host": "zcode", "id": "sess_demo"}],
            "current_evidence": ["https://example.com/proof"],
        }
        with tempfile.TemporaryDirectory() as directory:
            errors = casebook.validate_incidents(
                [incident], root=Path(directory), check_paths=True)
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
