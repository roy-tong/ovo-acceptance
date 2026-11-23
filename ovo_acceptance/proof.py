from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from . import model

PROOF_SCHEMA = "ovo.proof/1"
CHECKS_SCHEMA = "ovo.proof-checks/1"
REPLAY_SCHEMA = "ovo.replay-manifest/1"

LEVELS = ("P0", "P1", "P2", "P3", "P4")
STATUSES = ("PASS", "FAIL", "UNCHECKED", "INDETERMINATE", "EXPIRED")
EXECUTOR_OBSERVED = "executor_observed"
INDEPENDENT_STATE = "independent_state"
INDEPENDENT_VALIDATOR = "independent_validator"
EXTERNAL_OBSERVATION = "external_observation"
INDEPENDENCE = (
    EXECUTOR_OBSERVED, INDEPENDENT_STATE,
    INDEPENDENT_VALIDATOR, EXTERNAL_OBSERVATION,
)
REQUIRED_INDEPENDENCE = {
    "P2": INDEPENDENT_STATE,
    "P3": INDEPENDENT_VALIDATOR,
    "P4": EXTERNAL_OBSERVATION,
}


def _error(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _safe_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a non-empty relative string")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path must stay inside the proof bundle")
    root_resolved = root.resolve()
    resolved = (root / candidate).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError("path must stay inside the proof bundle")
    return resolved


def _load(path: Path, errors: List[Dict[str, str]]) -> Dict[str, Any]:
    try:
        return model.load_json(path)
    except model.AcceptanceError as exc:
        errors.append(_error("INVALID_JSON", str(path), str(exc)))
        return {}


def _check_shape(check: Dict[str, Any], index: int,
                 errors: List[Dict[str, str]]) -> None:
    path = "checks[%d]" % index
    for field in ("check_id", "claim", "scope"):
        if not isinstance(check.get(field), str) or not check[field].strip():
            errors.append(_error("REQUIRED", path + "." + field,
                                 "must be a non-empty string"))
    if check.get("level") not in LEVELS:
        errors.append(_error("ENUM", path + ".level",
                             "must be one of %s" % ", ".join(LEVELS)))
    status = check.get("status")
    if status not in STATUSES:
        errors.append(_error("ENUM", path + ".status",
                             "must be one of %s" % ", ".join(STATUSES)))
    checker = check.get("checker")
    if not isinstance(checker, dict):
        errors.append(_error("TYPE", path + ".checker", "must be an object"))
        checker = {}
    for field in ("name", "version"):
        if not isinstance(checker.get(field), str) or not checker[field].strip():
            errors.append(_error("REQUIRED", path + ".checker." + field,
                                 "must be a non-empty string"))
    if checker.get("independence") not in INDEPENDENCE:
        errors.append(_error("ENUM", path + ".checker.independence",
                             "must be one of %s" % ", ".join(INDEPENDENCE)))
    refs = check.get("evidence_refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        errors.append(_error("TYPE", path + ".evidence_refs",
                             "must be an array of evidence ids"))
    if status in ("PASS", "FAIL") and not refs:
        code = "PASS_WITHOUT_EVIDENCE" if status == "PASS" else "FAIL_WITHOUT_EVIDENCE"
        errors.append(_error(code, path + ".evidence_refs",
                             "%s must cite registered evidence" % status))
    if status in ("UNCHECKED", "INDETERMINATE", "EXPIRED") \
            and not isinstance(check.get("reason"), str):
        errors.append(_error("REASON_REQUIRED", path + ".reason",
                             "%s needs a human-readable reason" % status))
    elif status in ("UNCHECKED", "INDETERMINATE", "EXPIRED") \
            and not check.get("reason", "").strip():
        errors.append(_error("REASON_REQUIRED", path + ".reason",
                             "%s needs a human-readable reason" % status))
    required = REQUIRED_INDEPENDENCE.get(str(check.get("level") or ""))
    if status == "PASS" and required \
            and checker.get("independence") != required:
        errors.append(_error(
            "INDEPENDENCE_REQUIRED", path + ".checker.independence",
            "%s PASS requires %s" % (check.get("level"), required)))


def _result(bundle: Dict[str, Any], checks_doc: Dict[str, Any],
            errors: List[Dict[str, str]], time_semantics: Dict[str, Any] = None) -> Dict[str, Any]:
    rows = checks_doc.get("checks")
    checks = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    counts_by_level = {level: 0 for level in LEVELS}
    counts_by_status = {status: 0 for status in STATUSES}
    for check in checks:
        if check.get("level") in LEVELS:
            counts_by_level[check["level"]] += 1
        if check.get("status") in STATUSES:
            counts_by_status[check["status"]] += 1
    if errors:
        status = "INVALID"
    elif not checks:
        status = "BLOCKED"
        errors.append(_error("NO_CHECKS", "checks", "at least one check is required"))
    elif counts_by_status["FAIL"]:
        status = "FAIL"
    elif counts_by_status["UNCHECKED"] or counts_by_status["INDETERMINATE"]:
        status = "BLOCKED"
    elif counts_by_status["EXPIRED"]:
        status = "EXPIRED"
    else:
        status = "PASS"
    if time_semantics and time_semantics.get("status") == "UNCERTAIN" and status == "PASS":
        status = "INDETERMINATE"
    return {
        "schema": "ovo.proof-validation/1",
        "ok": status == "PASS" and not errors,
        "status": status,
        "proof_id": bundle.get("proof_id"),
        "contract_id": checks_doc.get("contract_id"),
        "counts_by_level": counts_by_level,
        "counts_by_status": counts_by_status,
        "checks": checks,
        "errors": errors,
        "time_semantics": time_semantics or {"status": "EXPLICIT", "timezone_assumed": None, "paths": []},
        "causality": "not_claimed",
    }


def validate_proof_bundle(path: str | Path) -> Dict[str, Any]:
    root = Path(path)
    errors: List[Dict[str, Any]] = []
    bundle = _load(root / "bundle.json", errors)
    contract = _load(root / "contract.json", errors)
    checks_doc = _load(root / "checks.json", errors)
    proof_doc = _load(root / "proof.json", errors)
    acceptance_verdict = None
    if not bundle:
        errors.append(_error("MISSING_BUNDLE", "bundle.json", "a non-empty acceptance bundle is required"))
    else:
        acceptance = model.validate_bundle(bundle)
        acceptance_verdict = acceptance.get("verdict")
        for item in acceptance["errors"]:
            errors.append(_error("ACCEPTANCE_" + item["code"], item["path"], item["message"]))
    if bundle and contract != bundle.get("task_contract"):
        errors.append(_error(
            "CONTRACT_PROJECTION_MISMATCH", "contract.json",
            "must be the exact task_contract projection from bundle.json"))
    trace_path = root / "trace.jsonl"
    trace_steps = []
    try:
        for line_number, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("line %d is not an object" % line_number)
            trace_steps.append(value)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(_error("INVALID_TRACE", "trace.jsonl", str(exc)))
    if bundle and trace_steps != (bundle.get("execution_trace") or {}).get("steps", []):
        errors.append(_error(
            "TRACE_PROJECTION_MISMATCH", "trace.jsonl",
            "must contain the execution_trace steps in their original order"))
    if checks_doc.get("schema") != CHECKS_SCHEMA:
        errors.append(_error("SCHEMA", "checks.schema", "must be %s" % CHECKS_SCHEMA))
    if bundle and checks_doc.get("contract_id") != (bundle.get("task_contract") or {}).get("contract_id"):
        errors.append(_error("CONTRACT_MISMATCH", "checks.contract_id",
                             "must match the task contract"))
    checks = checks_doc.get("checks")
    if not isinstance(checks, list):
        errors.append(_error("TYPE", "checks.checks", "must be an array"))
        checks = []
    evidence_ids = {
        entry.get("evidence_id")
        for entry in ((bundle.get("evidence_ledger") or {}).get("entries") or [])
        if isinstance(entry, dict)
    }
    seen_check_ids = set()
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(_error("TYPE", "checks[%d]" % index, "must be an object"))
            continue
        _check_shape(check, index, errors)
        check_id = check.get("check_id")
        if isinstance(check_id, str) and check_id in seen_check_ids:
            errors.append(_error("DUPLICATE_ID", "checks[%d].check_id" % index,
                                 "duplicate check id %r" % check_id))
        if isinstance(check_id, str):
            seen_check_ids.add(check_id)
        refs = check.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if isinstance(ref, str) and ref not in evidence_ids:
                errors.append(_error("UNKNOWN_EVIDENCE", "checks[%d].evidence_refs" % index,
                                     "evidence %r is not in the acceptance ledger" % ref))
    if proof_doc.get("schema") != PROOF_SCHEMA:
        errors.append(_error("SCHEMA", "proof.schema", "must be %s" % PROOF_SCHEMA))
    if bundle and proof_doc.get("contract_id") != (bundle.get("task_contract") or {}).get("contract_id"):
        errors.append(_error("CONTRACT_MISMATCH", "proof.contract_id",
                             "must match the task contract"))
    artifacts = proof_doc.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append(_error("TYPE", "proof.artifacts", "must be an array"))
        artifacts = []
    seen_artifact_ids = set()
    for index, artifact in enumerate(artifacts):
        path = "proof.artifacts[%d]" % index
        if not isinstance(artifact, dict):
            errors.append(_error("TYPE", path, "must be an object"))
            continue
        artifact_id = artifact.get("artifact_id")
        if artifact_id in seen_artifact_ids:
            errors.append(_error("DUPLICATE_ID", path + ".artifact_id", "duplicate artifact id"))
        seen_artifact_ids.add(artifact_id)
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or not model.HASH_RE.match(digest):
            errors.append(_error("HASH_FORMAT", path + ".sha256",
                                 "must be sha256:<64 lowercase hex>"))
        try:
            artifact_path = _safe_path(root, artifact.get("path"))
            if not artifact_path.is_file():
                errors.append(_error("ARTIFACT_MISSING", path + ".path", "artifact file not found"))
            elif isinstance(digest, str) and model.HASH_RE.match(digest):
                actual = "sha256:" + hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if actual != digest:
                    errors.append(_error("ARTIFACT_HASH_MISMATCH", path + ".sha256",
                                         "artifact bytes do not match the recorded hash"))
        except ValueError as exc:
            errors.append(_error("UNSAFE_PATH", path + ".path", str(exc)))
    replay = proof_doc.get("replay")
    if not isinstance(replay, dict):
        errors.append(_error("TYPE", "proof.replay", "must be an object"))
        replay = {}
    replay_doc = {}
    try:
        replay_path = _safe_path(root, replay.get("manifest"))
        replay_doc = _load(replay_path, errors)
    except ValueError as exc:
        errors.append(_error("UNSAFE_PATH", "proof.replay.manifest", str(exc)))
    if replay_doc.get("schema") != REPLAY_SCHEMA:
        errors.append(_error("SCHEMA", "replay.schema", "must be %s" % REPLAY_SCHEMA))
    if bundle and replay_doc.get("contract_id") != (bundle.get("task_contract") or {}).get("contract_id"):
        errors.append(_error("CONTRACT_MISMATCH", "replay.contract_id",
                             "must match the task contract"))
    replay_status = replay_doc.get("status")
    if replay_status not in ("AVAILABLE", "UNAVAILABLE"):
        errors.append(_error("ENUM", "replay.status", "must be AVAILABLE or UNAVAILABLE"))
    if replay.get("status") != replay_status:
        errors.append(_error("REPLAY_STATUS_MISMATCH", "proof.replay.status",
                             "must match the replay manifest"))
    missing_lists = (replay.get("missing"), replay_doc.get("missing"))
    if not all(isinstance(items, list) and all(isinstance(item, str) for item in items)
               for items in missing_lists):
        errors.append(_error("TYPE", "replay.missing", "both missing lists must contain strings"))
    elif set(missing_lists[0]) != set(missing_lists[1]):
        errors.append(_error("REPLAY_GAP_MISMATCH", "proof.replay.missing",
                             "must identify the same missing inputs as the replay manifest"))
    if replay_status == "AVAILABLE" and replay_doc.get("missing"):
        errors.append(_error("REPLAY_INPUT_MISSING", "replay.missing",
                             "an available replay cannot require missing inputs"))
    commands = replay_doc.get("commands")
    if not isinstance(commands, list):
        errors.append(_error("TYPE", "replay.commands", "must be an array"))
    if replay_status == "AVAILABLE" and not commands:
        errors.append(_error("REPLAY_COMMAND_REQUIRED", "replay.commands",
                             "an available replay needs at least one command"))
    if replay_status == "UNAVAILABLE" and not replay_doc.get("missing"):
        errors.append(_error("REPLAY_GAP_REQUIRED", "replay.missing",
                             "an unavailable replay must name missing inputs"))
    result = _result(proof_doc, checks_doc, errors, model.time_semantics(bundle))
    result["proof_id"] = proof_doc.get("proof_id")
    result["acceptance_verdict"] = acceptance_verdict
    if not errors and acceptance_verdict == "FAIL" and result["status"] != "FAIL":
        result["status"] = "FAIL"
        result["ok"] = False
    elif not errors and acceptance_verdict == "BLOCKED" and result["status"] == "PASS":
        result["status"] = "BLOCKED"
        result["ok"] = False
    result["contract_validation"] = {"status": "FAIL" if errors else "PASS", "errors": errors}
    result["business_verdict"] = {
        "status": result["status"], "counts_by_status": result["counts_by_status"],
    }
    return result
