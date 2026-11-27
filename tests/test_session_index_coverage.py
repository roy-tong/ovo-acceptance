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

    def test_merges_legacy_archive_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current"
            archive = root / "archive"
            current.mkdir()
            archive.mkdir()
            event = {"type": "session", "id": "legacy-1", "createdAt": 1794763200000,
                     "cwd": "/Users/demo/ovo family"}
            (archive / "session.jsonl").write_text(json.dumps(event), encoding="utf-8")
            rows = casebook.build_aux_session_index(
                root / "missing-codex", current, dsh_archive_root=archive)
        self.assertEqual(["legacy-1"], [row["id"] for row in rows])

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


class ClaudeCollectorTests(unittest.TestCase):
    def test_reads_top_level_sessions_and_excludes_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "project" / "claude-1.jsonl"
            session.parent.mkdir()
            lines = [
                {"type": "user", "sessionId": "claude-1", "cwd": "/demo/ovo family",
                 "timestamp": "2026-11-24T10:00:00Z",
                 "message": {"role": "user", "content": "用 Askovo 做高尔夫研究"}},
                {"type": "assistant", "sessionId": "claude-1", "isApiErrorMessage": True,
                 "timestamp": "2026-11-24T10:01:00Z", "message": {"role": "assistant", "content": []}},
            ]
            session.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in lines), encoding="utf-8")
            subagent = session.parent / "claude-1" / "subagents" / "agent-1.jsonl"
            subagent.parent.mkdir(parents=True)
            subagent.write_text(json.dumps(lines[0], ensure_ascii=False), encoding="utf-8")
            rows = list(casebook._claude_sessions(root))
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("claude", row["host"])
        self.assertEqual("claude-1", row["id"])
        self.assertEqual("用 Askovo 做高尔夫研究", row["title"])
        self.assertEqual(1, row["failed_turns"])
        self.assertEqual(["Askovo"], row["candidate_products"])
        self.assertIsNotNone(row["date"])


class ZcodeDbCollectorTests(unittest.TestCase):
    def test_reads_only_root_sessions_and_turn_metrics(self) -> None:
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "db.sqlite"
            con = sqlite3.connect(db)
            con.execute("create table session (id text, parent_id text, title text, directory text, time_created integer, time_updated integer, last_outcome text)")
            con.execute("create table turn_usage (session_id text, status text, tool_error_count integer, tool_call_count integer)")
            con.execute("insert into session values ('root-1', null, 'Gmail 外联复盘', '/demo/AgentMeasure', 1000, 2000, 'completed')")
            con.execute("insert into session values ('child-1', 'root-1', '子任务', '/demo/AgentMeasure', 1000, 2000, 'completed')")
            con.execute("insert into turn_usage values ('root-1', 'completed', 2, 9)")
            con.commit()
            con.close()
            rows = list(casebook._zcode_db_sessions(db))
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("root-1", row["id"])
        self.assertEqual("zcode", row["host"])
        self.assertEqual(1, row["turns"])
        self.assertEqual(0, row["failed_turns"])
        self.assertEqual(2, row["tool_errors"])
        self.assertEqual(9, row["tool_calls"])
        self.assertIn("Growovo", row["candidate_products"])


class IntentContractTests(unittest.TestCase):
    def test_validates_curated_user_intent_and_case_link(self) -> None:
        intent = {
            "intent_id": "UI-GTM-001",
            "case_id": "G-DEMO-01",
            "title": "检查并回复真实入站消息",
            "source_sessions": [{"host": "dsh", "id": "session-demo"}],
            "user_goal": "所有真实待回消息得到处理",
            "requested_tasks": ["检查 Gmail", "回复合格消息"],
            "acceptance": ["每条消息有处理状态", "无外部重放发送"],
            "constraints": ["测试不重新外发"],
            "test_status": "covered",
            "replay_mode": "evidence_only",
            "sensitivity": "private",
        }
        cases = [{"case_id": "G-DEMO-01"}]
        self.assertEqual([], casebook.validate_intents([intent], cases=cases))
        invalid = dict(intent, acceptance=[])
        self.assertTrue(any("acceptance" in error for error in casebook.validate_intents([invalid], cases=cases)))
        unknown = dict(intent, case_id="G-UNKNOWN")
        self.assertTrue(any("unknown case_id" in error for error in casebook.validate_intents([unknown], cases=cases)))


class SceneCaseCompletenessTests(unittest.TestCase):
    def test_requires_full_seven_node_context_and_unknown_reasons(self) -> None:
        scene_case = {
            "scene": {"trigger": "月度关账", "environment": "企业 AI 采购", "task_context": "付款前复核"},
            "user": {"role": "FinOps", "state": "已有账单", "decision_role": "决定是否付款"},
            "pain": {"current_substitute": "手工对账", "friction_cost": "逐行核对", "consequence": "可能错付"},
            "need": {"desired_outcome": "知道哪些金额可证明", "constraints": "缺证不猜", "measure": "覆盖率和未决项"},
            "feature": {"capability": "逐行复算", "acceptance_conditions": ["金额和证据可回链"], "alternatives_considered": ["人工对账"]},
            "product": {"form": "本地报告", "scope": "一个账期", "non_goals": ["不自动付款"], "acceptance_criteria": ["差异可读"]},
            "business": {"market_definition": "AI 采购账期", "geographies": "未指定", "time_window": "一个账期", "included_markets": "AI 服务买方", "excluded_markets": "个人报销", "target_segment": "FinOps", "payer": "企业买方", "positioning": "独立复核", "revenue_model": "按账期", "pricing_hypothesis": "未知", "cost_drivers": "人工复核", "unit_economics_inputs": "未知", "success_metrics": "下一次复核", "gate": "未验证不扩量"},
            "evidence": {"data_basis": "原始账单和会话", "user_voices": {"status": "unavailable", "reason": "原始 prompt 未复制"}},
            "acceptance": {"criteria": ["金额可复核"], "constraints": ["不执行付款"]},
            "provenance": {"status": "mixed", "notes": "任务真实，商业效果未知"},
            "unknowns": [{"field": "business.pricing_hypothesis", "reason": "未获得报价证据"}],
        }
        case = {"case_id": "DEMO", "scene_case": scene_case}
        self.assertEqual([], casebook.validate_scene_case(case))
        missing = dict(case, scene_case=dict(scene_case, pain={}))
        self.assertTrue(any("pain.current_substitute" in error for error in casebook.validate_scene_case(missing)))
        bad_unknown = dict(case, scene_case=dict(scene_case, unknowns=[{"field": "business.payer"}]))
        self.assertTrue(any("unknown reason" in error for error in casebook.validate_scene_case(bad_unknown)))


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
