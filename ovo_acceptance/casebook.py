#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PRODUCT_PATTERNS = {
    "Askovo": re.compile(r"askovo|SURE|高尔夫|省钱小助手|七节点|HMC|用户研究|场景.{0,12}用户.{0,12}需求", re.I),
    "Growovo": re.compile(r"growovo|GTM|增长|launch|营销|发帖|回帖|外联|KOC|获客|运营", re.I),
    "Verovo": re.compile(r"verovo|agentmeasure|buyer.?ledger|核验|账期|对账|费用审计|回执核验", re.I),
}
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"ak_live_[0-9A-Za-z_-]+"),
    re.compile(r"sk-[0-9A-Za-z_-]{16,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r'"(?:access_token|refresh_token|api_secret|client_secret)"\s*:\s*"[^"]{8,}"', re.I),
]
STATUSES = {"delivered", "partial", "learning", "needs_relink"}
REPLAY_MODES = {"askovo_study", "growovo_retro", "growovo_reply_case", "golden_script", "artifact_audit", "manual_only", "not_ready"}
OVO_PATH_RE = re.compile(r"ovo family|Askovo|Growovo|Verovo|askovo", re.I)
OVO_EXPLICIT_RE = re.compile(
    r"askovo|growovo|verovo|ovo family|agentmeasure|buyer.?ledger", re.I)


def load_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected object")
            rows.append(row)
    return rows


def write_jsonl(path, rows):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _products(text):
    return [name for name, pattern in PRODUCT_PATTERNS.items() if pattern.search(text)]


def _kimi_sessions(root):
    for state_path in sorted(Path(root).glob("*/session_*/state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        prompts = []
        wire = state_path.parent / "agents/main/wire.jsonl"
        if wire.exists():
            with wire.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "context.append_message":
                        continue
                    message = event.get("message", {})
                    if message.get("role") != "user" or message.get("origin", {}).get("kind") != "user":
                        continue
                    text = "\n".join(part.get("text", "") for part in message.get("content", []) if part.get("type") == "text").strip()
                    if text:
                        prompts.append(text)
        text = state.get("title", "") + "\n" + "\n".join(prompts)
        yield {
            "host": "kimi-code",
            "id": state.get("id") or state_path.parent.name,
            "date": state.get("createdAt"),
            "updated": state.get("updatedAt"),
            "title": state.get("title") or state_path.parent.name,
            "cwd": state.get("cwd"),
            "prompt_count": len(prompts),
            "candidate_products": _products(text),
            "source_ref": str(state_path),
        }


def _zcode_sessions(root):
    for digest in sorted(Path(root).glob("digest_*.jsonl")):
        for row in load_jsonl(digest):
            text = row.get("title", "") + "\n" + "\n".join(row.get("prompts", []))
            yield {
                "host": "zcode",
                "id": row.get("id"),
                "date": row.get("date"),
                "updated": None,
                "title": row.get("title") or row.get("id"),
                "cwd": row.get("dir"),
                "prompt_count": row.get("n_prompts", len(row.get("prompts", []))),
                "candidate_products": _products(text),
                "source_ref": f"{digest}#{row.get('id')}",
            }


def build_session_index(kimi_root, zcode_digest_root):
    rows = list(_kimi_sessions(kimi_root)) + list(_zcode_sessions(zcode_digest_root))
    return sorted(rows, key=lambda row: (row.get("date") or 0, row["host"], row["id"]))


def _timestamp_ms(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _safe_title(text):
    text = " ".join(str(text or "").split())[:180]
    if any(pattern.search(text) for pattern in SECRET_PATTERNS) or re.search(r"(?i)api.?key|app.?secret|password|token|私钥|密码", text):
        return "敏感配置任务"
    return text or "未命名任务"


def _codex_file_sessions(codex_root):
    codex_root = Path(codex_root)
    titles = {}
    index_path = codex_root / "session_index.jsonl"
    if index_path.exists():
        for row in load_jsonl(index_path):
            titles[row["id"]] = row.get("thread_name")
    paths = list((codex_root / "sessions").glob("2026/**/*.jsonl")) + list((codex_root / "archived_sessions").glob("*.jsonl")) + list((codex_root / "archived_sessions").glob("*.zst"))
    for path in paths:
        try:
            if path.suffix == ".zst":
                import zstandard
                lines = zstandard.ZstdDecompressor().decompress(path.read_bytes()).decode("utf-8", "replace").splitlines()
            else:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError):
            continue
        meta = {}
        texts = []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload") or {}
            if event.get("type") == "session_meta":
                meta = payload
            if payload.get("type") == "message" and payload.get("role") == "user":
                text = " ".join(part.get("text", "") for part in payload.get("content", []) if isinstance(part, dict)).strip()
                if text and not text.startswith(("# AGENTS.md", "<environment_context", "<external_", "Current runtime context")):
                    texts.append(text)
        session_id = meta.get("id") or meta.get("session_id") or path.stem
        title = titles.get(session_id) or _safe_title(texts[0] if texts else path.stem)
        yield {
            "host": "codex",
            "id": session_id,
            "date": _timestamp_ms(meta.get("timestamp")),
            "updated": None,
            "title": title,
            "cwd": meta.get("cwd"),
            "prompt_count": len(texts),
            "candidate_products": _products(title + "\n" + "\n".join(texts)),
            "source_ref": str(path),
            "turns": 0,
            "failed_turns": 0,
            "interrupted_turns": 0,
        }


def _codex_db_sessions(codex_root):
    db = Path(codex_root) / "thread_history_1.sqlite"
    if not db.exists():
        return
    import sqlite3
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    cur = con.cursor()
    turns = {}
    for thread_id, status in cur.execute("select thread_id,status from thread_turns"):
        row = turns.setdefault(thread_id, {"turns": 0, "failed_turns": 0, "interrupted_turns": 0})
        row["turns"] += 1
        if status == "failed":
            row["failed_turns"] += 1
        elif status == "interrupted":
            row["interrupted_turns"] += 1
    messages = {}
    for thread_id, data in cur.execute("select thread_id,item_json from thread_items where item_type='userMessage' order by created_at_ms"):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        text = payload.get("text") or " ".join(part.get("text", "") for part in payload.get("content", []) if isinstance(part, dict))
        if text:
            messages.setdefault(thread_id, []).append(text)
    for thread_id, texts in messages.items():
        row = turns.get(thread_id, {"turns": 0, "failed_turns": 0, "interrupted_turns": 0})
        yield {
            "host": "codex",
            "id": thread_id,
            "date": None,
            "updated": None,
            "title": _safe_title(texts[0]),
            "cwd": None,
            "prompt_count": len(texts),
            "candidate_products": _products("\n".join(texts)),
            "source_ref": f"{db}#{thread_id}",
            **row,
        }


def _read_session_lines(path: Path):
    if path.suffix in (".zst", ".zstd"):
        import zstandard
        with path.open("rb") as handle:
            return zstandard.ZstdDecompressor().stream_reader(handle).read().decode(
                "utf-8", "replace").splitlines()
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _dsh_sessions(dsh_root):
    root = Path(dsh_root)
    paths = sorted(root.rglob("session*.jsonl*")) if root.exists() else []
    for path in paths:
        meta = {}
        title = None
        texts = []
        try:
            lines = _read_session_lines(path)
        except (OSError, ValueError):
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = event.get("data") or {}
            if event.get("type") == "session":
                meta = event
            elif event.get("type") == "session/title":
                title = data.get("title")
            elif event.get("type") == "user/message":
                text = "\n".join(
                    part.get("text", "") for part in data.get("content", [])
                    if isinstance(part, dict)).strip()
                if text:
                    texts.append(text)
        session_id = meta.get("id") or path.parent.name
        cwd = meta.get("cwd")
        text = "\n".join(texts)
        if not (OVO_PATH_RE.search(str(cwd or ""))
                or OVO_EXPLICIT_RE.search((title or "") + "\n" + text)):
            continue
        yield {
            "host": "dsh",
            "id": session_id,
            "date": _timestamp_ms(meta.get("createdAt")),
            "updated": None,
            "title": title or _safe_title(texts[0] if texts else path.parent.name),
            "cwd": cwd,
            "prompt_count": len(texts),
            "candidate_products": _products(text),
            "source_ref": str(path),
            "turns": 0,
            "failed_turns": 0,
            "interrupted_turns": 0,
        }


def _conversation_id(key: str) -> str:
    if ":conversation:" in key:
        return key.split(":conversation:", 1)[1].split(":", 1)[0]
    return key.rsplit(":", 1)[-1]


def _by_conversation(mapping):
    return {_conversation_id(key): value for key, value in mapping.items()}


def _kimi_work_sessions(root):
    root = Path(root)
    titles_path = root / "conversation-titles.json"
    if not titles_path.exists():
        return
    try:
        titles = _by_conversation(json.loads(titles_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return

    def optional(name):
        path = root / name
        if not path.exists():
            return {}
        try:
            return _by_conversation(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {}

    statuses = optional("conversation-statuses.json")
    projects = optional("conversation-projects.json")
    usage = optional("conversation-context-usage.json")
    turn_counts = {}
    metrics = {}
    metrics_path = root / "segment-turn-metrics.json"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metrics = {}
    for key, value in metrics.items():
        conversation_id = _conversation_id(key)
        counts = turn_counts.setdefault(
            conversation_id, {"turns": 0, "failed_turns": 0, "interrupted_turns": 0})
        counts["turns"] += 1
        status = (value or {}).get("finishStatus")
        if status == "failed":
            counts["failed_turns"] += 1
        elif status == "interrupted":
            counts["interrupted_turns"] += 1

    for conversation_id, title in titles.items():
        context = usage.get(conversation_id) or {}
        counts = turn_counts.get(
            conversation_id, {"turns": 0, "failed_turns": 0, "interrupted_turns": 0})
        cwd = projects.get(conversation_id)
        yield {
            "host": "kimi-work",
            "id": conversation_id,
            "date": _timestamp_ms(context.get("updatedAt")),
            "updated": context.get("updatedAt"),
            "title": title or conversation_id,
            "cwd": cwd,
            "prompt_count": counts["turns"],
            "candidate_products": _products((title or "") + "\n" + (cwd or "")),
            "source_ref": str(root / "conversation-titles.json"),
            "turns": counts["turns"],
            "failed_turns": counts["failed_turns"],
            "interrupted_turns": counts["interrupted_turns"],
            "model": context.get("model"),
            "status": statuses.get(conversation_id),
        }


def build_aux_session_index(codex_root, dsh_root, kimi_work_root=None):
    rows = {}
    for row in _codex_file_sessions(codex_root):
        rows[row["id"]] = row
    for row in _codex_db_sessions(codex_root):
        if row["id"] in rows:
            existing = rows[row["id"]]
            existing["related_refs"] = [existing["source_ref"], row["source_ref"]]
            existing["prompt_count"] = max(existing["prompt_count"], row["prompt_count"])
            existing["candidate_products"] = sorted(set(existing["candidate_products"] + row["candidate_products"]))
            existing["turns"] = row["turns"]
            existing["failed_turns"] = row["failed_turns"]
            existing["interrupted_turns"] = row["interrupted_turns"]
            if not existing.get("date"):
                existing["date"] = row.get("date")
        else:
            rows[row["id"]] = row
    for row in _dsh_sessions(dsh_root):
        rows[row["id"]] = row
    if kimi_work_root:
        for row in _kimi_work_sessions(kimi_work_root):
            rows[row["id"]] = row
    return sorted(rows.values(), key=lambda row: (row.get("date") or 0, row["host"], row["id"]))


def validate_incidents(incidents, *, root, check_paths=True):
    errors = []
    seen = set()
    required = ("incident_id", "case_id", "title", "status", "symptom", "root_cause", "resolution", "source_sessions", "current_evidence")
    for index, incident in enumerate(incidents):
        label = incident.get("incident_id") or f"row {index + 1}"
        for key in required:
            if key not in incident:
                errors.append(f"{label}: missing {key}")
        incident_id = incident.get("incident_id")
        if incident_id in seen:
            errors.append(f"duplicate incident_id: {incident_id}")
        seen.add(incident_id)
        if incident.get("status") not in {"fixed", "mitigated", "recurring", "open", "external", "unknown"}:
            errors.append(f"{label}: invalid status")
        if not incident.get("source_sessions"):
            errors.append(f"{label}: source_sessions must not be empty")
        for evidence in incident.get("current_evidence", []):
            path = evidence.get("path") if isinstance(evidence, dict) else evidence
            if not path:
                errors.append(f"{label}: invalid current evidence")
            elif check_paths and not _is_external_ref(path) \
                    and not _resolve(root, path).exists():
                errors.append(f"{label}: missing current evidence {path}")
        serialized = json.dumps(incident, ensure_ascii=False)
        if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
            errors.append(f"{label}: possible credential material")
    return errors


def render_incidents(incidents):
    counts = {status: sum(1 for row in incidents if row["status"] == status) for status in ("open", "recurring", "mitigated", "unknown", "external", "fixed")}
    lines = [
        "# OVO 执行问题与解决情况全景",
        "",
        "> 来源：Codex、DSH、Kimi Code、Kimi Work、ZCode 的逐步执行日志与 turn 指标。只保留问题结构与证据链接，不复制原始 prompt、凭据或联系人。",
        "",
        "## 状态总览",
        "",
        f"- 未解决：{counts['open']}",
        f"- 反复出现：{counts['recurring']}",
        f"- 部分缓解：{counts['mitigated']}",
        f"- 无法确认：{counts['unknown']}",
        f"- 外部中断：{counts['external']}",
        f"- 已固化：{counts['fixed']}",
        "",
        "状态含义：`fixed` 有当前代码/测试/运行证据；`mitigated` 只在受控范围改善；`recurring` 后续仍有同类表现；`open` 仍有明确未决项；`external` 是宿主或平台中断；`unknown` 不能凭历史摘要判断当前状态。",
        "",
    ]
    order = {"open": 0, "recurring": 1, "mitigated": 2, "unknown": 3, "external": 4, "fixed": 5}
    for row in sorted(incidents, key=lambda item: (order[item["status"]], item["incident_id"])):
        lines.extend([
            f"## {row['incident_id']}｜{row['title']}",
            "",
            f"- 状态：{row['status']}；关联案例：`{row['case_id']}`",
            f"- 症状：{row['symptom']}",
            f"- 根因：{row['root_cause']}",
            f"- 当时解决：{row['resolution']['then']}",
            f"- 当前证据：{row['resolution']['current']}",
            f"- 未解决/边界：{row['resolution']['unresolved']}",
            f"- 下一步：{row.get('next_action') or '保持现有边界并持续复核'}",
            "- 来源会话：" + "、".join(f"{session['host']}:{session['id']}" for session in row["source_sessions"]),
            "",
        ])
    return "\n".join(lines)


def _resolve(root, value):
    path = Path(value)
    return path if path.is_absolute() else Path(root) / path


def _is_external_ref(value) -> bool:
    return bool(re.match(r"^https?://", str(value or ""), re.I))


def validate_cases(cases, *, root, check_paths=True):
    errors = []
    required = ("case_id", "product", "title", "status", "time_window", "goal", "source_sessions", "artifacts", "outcome", "replay", "sensitivity")
    seen = set()
    for index, case in enumerate(cases):
        label = case.get("case_id") or f"row {index + 1}"
        for key in required:
            if key not in case:
                errors.append(f"{label}: missing {key}")
        case_id = case.get("case_id")
        if case_id in seen:
            errors.append(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        if case.get("product") not in {"Askovo", "Growovo", "Verovo", "Cross"}:
            errors.append(f"{label}: invalid product")
        if case.get("status") not in STATUSES:
            errors.append(f"{label}: invalid status")
        if not case.get("source_sessions"):
            errors.append(f"{label}: source_sessions must not be empty")
        for session in case.get("source_sessions", []):
            if not session.get("host") or not session.get("id"):
                errors.append(f"{label}: invalid source session")
        replay = case.get("replay") or {}
        if replay.get("mode") not in REPLAY_MODES:
            errors.append(f"{label}: invalid replay mode")
        if replay.get("mode") == "golden_script":
            if check_paths and not _resolve(root, replay.get("script", "")).is_file():
                errors.append(f"{label}: missing golden replay script {replay.get('script')}")
            if check_paths and not _resolve(root, replay.get("inputs", "")).exists():
                errors.append(f"{label}: missing golden replay inputs {replay.get('inputs')}")
        for artifact in case.get("artifacts", []):
            if not artifact.get("path"):
                errors.append(f"{label}: artifact missing path")
                continue
            if check_paths and artifact.get("required", True) \
                    and not _is_external_ref(artifact["path"]) \
                    and not _resolve(root, artifact["path"]).exists():
                errors.append(f"{label}: missing artifact {artifact['path']}")
        for key in ("artifact", "execution", "business", "adoption"):
            if key not in case.get("outcome", {}):
                errors.append(f"{label}: outcome missing {key}")
        serialized = json.dumps(case, ensure_ascii=False)
        for pattern in SECRET_PATTERNS:
            if pattern.search(serialized):
                errors.append(f"{label}: possible credential material")
                break
    return errors


def _run(command, *, cwd, log_path, timeout=300):
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    log_path.write_text("$ " + " ".join(map(str, command)) + "\n\n" + completed.stdout + completed.stderr, encoding="utf-8")
    return completed.returncode


def _check_expectations(workspace, replay):
    problems = []
    for relative in replay.get("expect_files", []):
        if not (workspace / relative).is_file():
            problems.append(f"missing expected file: {relative}")
    for relative, phrases in replay.get("expect_contains", {}).items():
        path = workspace / relative
        if not path.is_file():
            problems.append(f"missing content file: {relative}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for phrase in phrases:
            if phrase not in text:
                problems.append(f"{relative}: missing phrase {phrase!r}")
    return problems


def apply_replay_migrations(workspace, replay):
    platforms = replay.get("migrate_cdp") or []
    target = replay.get("cdp_engine_version")
    if not platforms:
        return []
    if not target:
        raise ValueError("cdp_engine_version is required for CDP migration")
    workspace = Path(workspace)
    study_path = workspace / "study.json"
    study = json.loads(study_path.read_text(encoding="utf-8"))
    adapters = study.get("source_adapters") or {}
    evidence_path = workspace / "02-data/evidence.jsonl"
    evidence = []
    if evidence_path.exists():
        evidence = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    changes = []
    for platform in platforms:
        adapter = adapters.get(platform) or {}
        if adapter.get("access_basis") != "cdp_authorized_visible_page":
            continue
        previous = adapter.get("connector_revision")
        conflicting = [row for row in evidence if row.get("source_platform") == platform and row.get("connector_revision") != target]
        if conflicting:
            raise ValueError(f"{platform}: {len(conflicting)} evidence records require an explicit evidence migration")
        if previous == target:
            continue
        adapter["connector_revision"] = target
        changes.append({"platform": platform, "from": previous, "to": target})
    if changes:
        study_path.write_text(json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (workspace / "replay-migration.json").write_text(json.dumps({"type": "cdp_adapter_declaration_only", "evidence_changed": False, "changes": changes}, ensure_ascii=False, indent=2), encoding="utf-8")
    return changes


def _replay_askovo(case, *, root, run_dir):
    replay = dict(case["replay"])
    source = _resolve(root, replay["study_path"])
    if not source.is_dir():
        return {"status": "failed", "problems": [f"study not found: {source}"]}
    cli = _resolve(root, replay.get("cli") or "Askovo/skills/askovo/scripts/askovo.py")
    workspace = run_dir / "workspace"
    shutil.copytree(source, workspace)
    version_path = cli.parents[3] / "VERSION"
    if version_path.exists():
        replay.setdefault("cdp_engine_version", version_path.read_text(encoding="utf-8").strip())
    try:
        migrations = apply_replay_migrations(workspace, replay)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "failed", "verification_type": "task_rerun", "problems": [str(exc)]}
    command_results = []
    for index, command in enumerate(replay.get("commands") or [{"argv": ["check", "--stage", "full"], "expect_exit": 0}]):
        argv = command["argv"]
        full_command = [sys.executable, str(cli), argv[0], str(workspace)] + argv[1:]
        code = _run(full_command, cwd=run_dir, log_path=run_dir / f"command-{index + 1}.log")
        expected = command.get("expect_exit", 0)
        command_results.append({"argv": argv, "exit": code, "expected_exit": expected})
        if code != expected:
            return {"status": "failed", "verification_type": "task_rerun", "commands": command_results, "problems": [f"command exited {code}, expected {expected}"]}
    problems = _check_expectations(workspace, replay)
    return {"status": "passed" if not problems else "failed", "verification_type": "task_rerun", "commands": command_results, "workspace": str(workspace), "migrations": migrations, "problems": problems}


def _replay_growovo(case, *, root, run_dir):
    replay = case["replay"]
    cli = _resolve(root, replay.get("cli") or "Growovo/代码仓库/Growovo/mkt.py")
    facts = _resolve(root, replay["facts"])
    scan_path = _resolve(root, replay["scan_path"])
    report = run_dir / "retro.md"
    scan = run_dir / "scan.json"
    code = _run([sys.executable, str(cli), "retro", "report", "--facts", str(facts), "--path", str(scan_path), "--scan", str(scan), "--out", str(report)], cwd=run_dir, log_path=run_dir / "command-1.log")
    if code != 0:
        return {"status": "failed", "verification_type": "task_rerun", "problems": [f"retro report exited {code}"]}
    problems = _check_expectations(run_dir, {"expect_files": ["retro.md"], "expect_contains": {"retro.md": replay.get("expect_contains", [])}})
    return {"status": "passed" if not problems else "failed", "verification_type": "task_rerun", "report": str(report), "problems": problems}


def _replay_growovo_reply_case(case, *, root, run_dir):
    replay = case["replay"]
    cli = _resolve(root, replay.get("cli") or "Growovo/代码仓库/Growovo/mkt.py")
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True)
    accounts = json.loads(_resolve(root, replay["accounts"]).read_text(encoding="utf-8"))
    (data_dir / "accounts.json").write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
    messages = json.loads(_resolve(root, replay["messages"]).read_text(encoding="utf-8"))
    source = run_dir / "messages.jsonl"
    source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in messages), encoding="utf-8")
    account_id = accounts["accounts"][0]["id"]
    authorization = case["case_id"] + "-authorized-fixture"
    logs = []
    for index in range(2):
        code = _run([sys.executable, str(cli), "--workspace", str(data_dir), "grow", "reply", "import", str(source), "--account", account_id, "--channel", "email", "--by", "roy", "--authorization", authorization], cwd=run_dir, log_path=run_dir / f"import-{index + 1}.log")
        logs.append({"command": f"import-{index + 1}", "exit": code})
        if code != 0:
            return {"status": "failed", "verification_type": "task_rerun", "commands": logs, "problems": [f"import {index + 1} exited {code}"]}
    cases_path = data_dir / "replies/reply-cases.jsonl"
    records = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest = {}
    for record in records:
        latest[record["source_ref"]] = record
    for ref, label in replay.get("review", {}).items():
        case_id = latest[ref]["reply_case_id"]
        code = _run([sys.executable, str(cli), "--workspace", str(data_dir), "grow", "reply", "review", case_id, "--by", "roy", "--label", label], cwd=run_dir, log_path=run_dir / f"review-{ref}.log")
        logs.append({"command": f"review-{ref}", "exit": code})
        if code != 0:
            return {"status": "failed", "verification_type": "task_rerun", "commands": logs, "problems": [f"review {ref} exited {code}"]}
    for ref in replay.get("dnc", []):
        case_id = latest[ref]["reply_case_id"]
        code = _run([sys.executable, str(cli), "--workspace", str(data_dir), "grow", "reply", "dnc", case_id, "--by", "roy", "--reason", "explicit opt-out"], cwd=run_dir, log_path=run_dir / f"dnc-{ref}.log")
        logs.append({"command": f"dnc-{ref}", "exit": code})
        if code != 0:
            return {"status": "failed", "verification_type": "task_rerun", "commands": logs, "problems": [f"dnc {ref} exited {code}"]}
    records = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest = {}
    for record in records:
        latest[record["source_ref"]] = record
    problems = []
    if len(latest) != len(messages):
        problems.append(f"expected {len(messages)} cases, got {len(latest)}")
    for ref, label in replay.get("review", {}).items():
        if latest[ref].get("human_label") != label:
            problems.append(f"{ref}: expected human_label={label}, got {latest[ref].get('human_label')}")
    for ref in replay.get("dnc", []):
        if latest[ref].get("dnc_state") != "active":
            problems.append(f"{ref}: expected active DNC, got {latest[ref].get('dnc_state')}")
    imports_path = data_dir / "replies/reply-imports.jsonl"
    import_records = [json.loads(line) for line in imports_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not import_records or import_records[-1].get("created") != 0 or import_records[-1].get("skipped_duplicate") != len(messages):
        problems.append("second import did not deduplicate every message")
    summary = {ref: {"link_state": row.get("link_state"), "human_label": row.get("human_label"), "dnc_state": row.get("dnc_state"), "version": row.get("version")} for ref, row in latest.items()}
    return {"status": "passed" if not problems else "failed", "verification_type": "task_rerun", "commands": logs, "cases": summary, "problems": problems}


def _replay_golden_script(case, *, root, run_dir):
    replay = case["replay"]
    script = _resolve(root, replay["script"])
    substitutions = {"root": str(root), "run_dir": str(run_dir), "workspace": str(run_dir / "workspace")}
    path_flags = set(replay.get("path_args") or ["--cli", "--inputs", "--ocr-source"])
    argv = []
    previous = ""
    for value in replay.get("argv") or []:
        rendered = str(value).format(**substitutions)
        if previous in path_flags and rendered and not Path(rendered).is_absolute():
            rendered = str(_resolve(root, rendered))
        argv.append(rendered)
        previous = str(value)
    log_path = run_dir / "command-1.log"
    code = _run([sys.executable, str(script), *argv], cwd=run_dir, log_path=log_path,
                timeout=replay.get("timeout", 300))
    if code != 0:
        return {"status": "failed", "verification_type": "task_rerun",
                "problems": [f"golden script exited {code}"], "log": str(log_path)}
    try:
        text = log_path.read_text(encoding="utf-8").split("\n\n", 1)[1]
        result = json.loads(text)
    except (OSError, IndexError, json.JSONDecodeError) as exc:
        return {"status": "failed", "verification_type": "task_rerun",
                "problems": [f"golden script did not return a result JSON object: {exc}"],
                "log": str(log_path)}
    if result.get("external_writes"):
        result["status"] = "failed"
        result.setdefault("problems", []).append("golden replay declared external writes")
    result["verification_type"] = "task_rerun"
    result["log"] = str(log_path)
    result.setdefault("problems", [])
    return result


def replay_case(cases, case_id, *, root, run_root):
    case = next((row for row in cases if row.get("case_id") == case_id), None)
    if case is None:
        raise ValueError(f"unknown case_id: {case_id}")
    mode = case["replay"]["mode"]
    if mode in {"manual_only", "not_ready"}:
        return {"case_id": case_id, "status": "blocked", "verification_type": "none", "problems": [case["replay"].get("reason") or "case is not replayable"]}
    run_dir = Path(run_root) / case_id
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite replay directory: {run_dir}")
    run_dir.mkdir(parents=True)
    if mode == "askovo_study":
        result = _replay_askovo(case, root=root, run_dir=run_dir)
    elif mode == "growovo_retro":
        result = _replay_growovo(case, root=root, run_dir=run_dir)
    elif mode == "growovo_reply_case":
        result = _replay_growovo_reply_case(case, root=root, run_dir=run_dir)
    elif mode == "golden_script":
        result = _replay_golden_script(case, root=root, run_dir=run_dir)
    else:
        problems = []
        for artifact in case.get("artifacts", []):
            if artifact.get("required", True) and not _resolve(root, artifact["path"]).exists():
                problems.append(f"missing artifact: {artifact['path']}")
        for relative, phrases in case["replay"].get("expect_contains", {}).items():
            path = _resolve(root, relative)
            if not path.is_file():
                problems.append(f"missing content file: {relative}")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            problems.extend(f"{relative}: missing phrase {phrase!r}" for phrase in phrases if phrase not in text)
        result = {"status": "passed" if not problems else "failed", "verification_type": "evidence_only", "problems": problems}
    result["case_id"] = case_id
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def prune_replay_workspace(workspace):
    workspace = Path(workspace)
    removed = []
    for relative in ("02-data/raw", "02-data/normalized.jsonl", "02-data/views"):
        target = workspace / relative
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(relative)
        elif target.exists():
            target.unlink()
            removed.append(relative)
    return removed


def verify_cases(cases, *, root, run_root):
    run_dir = Path(run_root) / ("verification-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run_dir.mkdir(parents=True)
    results = []
    for case in cases:
        if case["replay"]["mode"] in {"manual_only", "not_ready"}:
            result = {"case_id": case["case_id"], "status": "blocked", "verification_type": "none", "problems": [case["replay"].get("reason") or "case is not replayable"]}
        else:
            result = replay_case(cases, case["case_id"], root=root, run_root=run_dir)
            if result["status"] == "passed" and result.get("verification_type") == "task_rerun" and result.get("workspace"):
                result["pruned_derived_copies"] = prune_replay_workspace(result["workspace"])
                (run_dir / case["case_id"] / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
    summary = {status: sum(1 for row in results if row["status"] == status) for status in ("passed", "failed", "blocked")}
    payload = {"run_dir": str(run_dir), "summary": summary, "results": results}
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _workspace_root(args, registry):
    if getattr(args, "root", None) and args.root != ".":
        return Path(args.root).resolve()
    if os.environ.get("OVO_CASE_ROOT"):
        return Path(os.environ["OVO_CASE_ROOT"]).resolve()
    if os.environ.get("OVO_CASE_REGISTRY"):
        return Path.cwd().resolve()
    return registry.parents[3].resolve()


def _run_root(args, registry):
    run_root = Path(args.run_root)
    if run_root.is_absolute():
        return run_root.resolve()
    return _workspace_root(args, registry) / run_root


def _default_registry() -> Path:
    relative = Path("ai输出/ovo-真实任务资产库/registry/cases.jsonl")
    source = Path(__file__).resolve()
    for ancestor in source.parents:
        candidate = ancestor / relative
        if candidate.is_file():
            return candidate
    return source.parents[2] / relative


def main(argv=None):
    parser = argparse.ArgumentParser(description="OVO real-task case library")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    incidents_parser = sub.add_parser("incidents")
    incidents_parser.add_argument("--out")
    index_parser = sub.add_parser("index")
    index_parser.add_argument("--kimi-root", default="/Users/tongxiarui/.kimi-code/sessions")
    index_parser.add_argument("--zcode-digest-root", default="/Users/tongxiarui/.zcode/tmp/memory-review")
    index_parser.add_argument("--codex-root", default=str(Path.home() / ".codex"))
    index_parser.add_argument("--dsh-root", default=str(Path.home() / ".dsh/sessions"))
    index_parser.add_argument(
        "--kimi-work-root",
        default=str(Path.home() / "Library/Application Support/kimi-desktop/kimi-agent"))
    index_parser.add_argument("--out", required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--root", default=".")
    validate_parser.add_argument("--skip-paths", action="store_true")
    show_parser = sub.add_parser("show")
    show_parser.add_argument("case_id")
    replay_parser = sub.add_parser("replay")
    replay_parser.add_argument("case_id")
    replay_parser.add_argument("--root", default=".")
    replay_parser.add_argument("--run-root", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--root", default=".")
    verify_parser.add_argument("--run-root", required=True)
    args = parser.parse_args(argv)
    registry = Path(os.environ.get("OVO_CASE_REGISTRY") or _default_registry())
    if args.action == "index":
        rows = build_session_index(args.kimi_root, args.zcode_digest_root) + build_aux_session_index(
            args.codex_root, args.dsh_root, args.kimi_work_root)
        rows.sort(key=lambda row: (row.get("date") or 0, row["host"], row["id"]))
        write_jsonl(args.out, rows)
        print(json.dumps({"sessions": len(rows), "out": args.out}, ensure_ascii=False))
        return 0
    cases = load_jsonl(registry)
    if args.action == "incidents":
        incident_path = registry.parent / "incidents.jsonl"
        text = render_incidents(load_jsonl(incident_path)) if incident_path.exists() else "No incidents recorded"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0
    if args.action == "list":
        for case in cases:
            print(f"{case['case_id']}\t{case['product']}\t{case['status']}\t{case['title']}")
        return 0
    if args.action == "show":
        case = next((row for row in cases if row["case_id"] == args.case_id), None)
        if case is None:
            print(f"unknown case_id: {args.case_id}", file=sys.stderr)
            return 2
        print(json.dumps(case, ensure_ascii=False, indent=2))
        return 0
    if args.action == "validate":
        errors = validate_cases(cases, root=_workspace_root(args, registry), check_paths=not args.skip_paths)
        incident_path = registry.parent / "incidents.jsonl"
        incidents = load_jsonl(incident_path) if incident_path.exists() else []
        incident_errors = validate_incidents(incidents, root=_workspace_root(args, registry), check_paths=not args.skip_paths)
        print(json.dumps({"cases": len(cases), "errors": errors, "incidents": len(incidents), "incident_errors": incident_errors}, ensure_ascii=False, indent=2))
        return 2 if errors or incident_errors else 0
    if args.action == "verify":
        result = verify_cases(cases, root=_workspace_root(args, registry), run_root=_run_root(args, registry))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["summary"]["failed"] == 0 else 2
    result = replay_case(cases, args.case_id, root=_workspace_root(args, registry), run_root=_run_root(args, registry))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
