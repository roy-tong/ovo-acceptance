"""Executable validation for the OVO shared acceptance layer.

Field-level rules live in ``contracts/*.schema.json`` (a small JSON-Schema
subset: type / enum / required / pattern / minItems / minimum / const). This
module walks those schemas and adds the cross-document rules a single document
cannot check:

* every PASS cites evidence registered in the same ledger;
* product observations carry version, permission, platform and region, and one
  observation never generalises to a universal capability;
* every FAIL has an escalation with a named decision maker;
* the bundle verdict treats UNPROVEN as not-passed.

Python 3.9+ standard library only.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BUNDLE_SCHEMA = "ovo.acceptance-bundle/1"
TASK_SCHEMA = "ovo.task-contract/1"
TRACE_SCHEMA = "ovo.execution-trace/1"
LEDGER_SCHEMA = "ovo.evidence-ledger/1"
ACCEPTANCE_SCHEMA = "ovo.acceptance-record/1"
ESCALATION_SCHEMA = "ovo.escalation-record/1"
AGENT_E2E_SCHEMA = "ovo.agent-e2e-run/1"
RESULT_RECEIPT_SCHEMA = "ovo.result-receipt/1"
DELEGATED_TASK_SCHEMA = "ovo.delegated-task/1"
SERVICE_CAPABILITY_SCHEMA = "ovo.service-capability/1"
EXPERIMENT_SCHEMA = "ovo.experiment-contract/1"

KIND_BY_SCHEMA = {
    TASK_SCHEMA: "task",
    TRACE_SCHEMA: "trace",
    LEDGER_SCHEMA: "evidence",
    ACCEPTANCE_SCHEMA: "acceptance",
    ESCALATION_SCHEMA: "escalation",
    AGENT_E2E_SCHEMA: "agent_e2e",
    RESULT_RECEIPT_SCHEMA: "result_receipt",
    DELEGATED_TASK_SCHEMA: "delegated_task",
    SERVICE_CAPABILITY_SCHEMA: "service_capability",
    EXPERIMENT_SCHEMA: "experiment",
}
SCHEMA_BY_KIND = {kind: schema for schema, kind in KIND_BY_SCHEMA.items()}

SCHEMA_FILES = {
    "task": "task-contract.schema.json",
    "trace": "execution-trace.schema.json",
    "evidence": "evidence-ledger.schema.json",
    "acceptance": "acceptance-record.schema.json",
    "escalation": "escalation-record.schema.json",
    "agent_e2e": "agent-e2e-run.schema.json",
    "result_receipt": "result-receipt.schema.json",
    "delegated_task": "delegated-task.schema.json",
    "service_capability": "service-capability.schema.json",
    "experiment": "experiment-contract.schema.json",
}

VERDICTS = ("PASS", "FAIL", "UNPROVEN", "NOT_APPLICABLE")
DECISIONS = ("accept_with_gap", "rework", "stop", "external_review")
TRIGGERS = ("failed_criterion", "unproven_evidence", "conflicting_evidence",
            "blocked_input", "permission")
GENERALIZATIONS = ("single_case", "repeated", "multi_context")
CONTEXT_FIELDS = ("product_version", "account_permission", "platform", "region")

DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_SOURCE_CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"
_CONTRACTS_DIR = _SOURCE_CONTRACTS_DIR if _SOURCE_CONTRACTS_DIR.is_dir() else Path(__file__).resolve().parent / "contracts"
_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


class AcceptanceError(ValueError):
    """Raised when a document cannot be read as acceptance evidence at all."""


def _error(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "path": path, "message": message}


def load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AcceptanceError("file not found: %s" % path) from exc
    except json.JSONDecodeError as exc:
        raise AcceptanceError("%s is not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(payload, dict):
        raise AcceptanceError("%s must contain one JSON object" % path)
    return payload


def load_schema(kind: str) -> Dict[str, Any]:
    if kind not in SCHEMA_FILES:
        raise AcceptanceError("unknown document kind: %s (use %s)"
                              % (kind, ", ".join(sorted(SCHEMA_FILES))))
    if kind not in _SCHEMA_CACHE:
        path = _CONTRACTS_DIR / SCHEMA_FILES[kind]
        _SCHEMA_CACHE[kind] = json.loads(path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[kind]


def detect_kind(doc: Dict[str, Any]) -> Optional[str]:
    return KIND_BY_SCHEMA.get(str(doc.get("schema") or ""))


def _join(path: str, key: str) -> str:
    return "%s.%s" % (path, key) if path else key


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _walk(value: Any, schema: Dict[str, Any], path: str,
          errors: List[Dict[str, str]]) -> None:
    expected = schema.get("type")
    if expected and not _type_ok(value, expected):
        errors.append(_error("TYPE", path or "$",
                             "expected %s, got %s" % (expected, type(value).__name__)))
        return
    if "const" in schema and value != schema["const"]:
        errors.append(_error("CONST", path or "$",
                             "must equal %r" % (schema["const"],)))
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(str(item) for item in schema["enum"])
        errors.append(_error("ENUM", path or "$",
                             "must be one of: %s (got %r)" % (allowed, value)))
    if isinstance(value, str):
        if "minLength" in schema and len(value.strip()) < int(schema["minLength"]):
            errors.append(_error("MIN_LENGTH", path or "$",
                                 "must be at least %d non-space characters"
                                 % int(schema["minLength"])))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(_error("PATTERN", path or "$",
                                 "does not match %s" % schema["pattern"]))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(_error("MIN_ITEMS", path or "$",
                                 "needs at least %d item(s)" % int(schema["minItems"])))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _walk(item, item_schema, "%s[%d]" % (path or "$", index), errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(_error("REQUIRED", _join(path, key),
                                     "missing required field"))
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(_error("UNKNOWN_FIELD", _join(path, key),
                                         "field is not part of this contract"))
        for key, sub_schema in properties.items():
            if key in value:
                _walk(value[key], sub_schema, _join(path, key), errors)
    if "minimum" in schema and isinstance(value, (int, float)) \
            and not isinstance(value, bool):
        if value < schema["minimum"]:
            errors.append(_error("MINIMUM", path or "$",
                                 "must be >= %s" % schema["minimum"]))


def _parse_instant(text: str) -> Optional[datetime]:
    if not isinstance(text, str) or not DATETIME_RE.match(text):
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _require_text(doc: Dict[str, Any], key: str, path: str,
                  errors: List[Dict[str, str]]) -> None:
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(_error("REQUIRED", _join(path, key),
                             "must be a non-empty string"))


def _schema_errors(doc: Dict[str, Any], kind: str) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    _walk(doc, load_schema(kind), "", errors)
    return errors


def _check_unique(ids: Iterable[str], path: str, errors: List[Dict[str, str]]) -> None:
    seen = set()
    for item in ids:
        if item in seen:
            errors.append(_error("DUPLICATE_ID", path, "duplicate id %r" % item))
        seen.add(item)


def validate_task_contract(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "task")
    if doc.get("schema") != TASK_SCHEMA:
        return errors
    deliverables = doc.get("deliverables") or []
    _check_unique([str(item.get("id") or "") for item in deliverables
                   if isinstance(item, dict)], "deliverables.id", errors)
    for index, item in enumerate(deliverables):
        if not isinstance(item, dict):
            continue
        criteria = item.get("acceptance_criteria") or []
        _check_unique([str(value) for value in criteria],
                      "deliverables[%d].acceptance_criteria" % index, errors)
    return errors


def validate_execution_trace(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "trace")
    if doc.get("schema") != TRACE_SCHEMA:
        return errors
    started = _parse_instant(doc.get("started_at", ""))
    finished = _parse_instant(doc.get("finished_at", ""))
    if started and finished and finished < started:
        errors.append(_error("TIME_ORDER", "finished_at",
                             "finished_at is earlier than started_at"))
    steps = doc.get("steps") or []
    index_by_id: Dict[str, int] = {}
    for position, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("step_id") or "")
        if step_id in index_by_id:
            errors.append(_error("DUPLICATE_ID", "steps[%d].step_id" % position,
                                 "duplicate step_id %r" % step_id))
        index_by_id.setdefault(step_id, position)
    for position, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        path = "steps[%d]" % position
        step_started = _parse_instant(step.get("started_at", ""))
        step_ended = _parse_instant(step.get("ended_at", ""))
        if step_started and step_ended and step_ended < step_started:
            errors.append(_error("TIME_ORDER", path + ".ended_at",
                                 "ended_at is earlier than started_at"))
        for link in ("retry_of", "cache_hit_of"):
            target = str(step.get(link) or "")
            if not target:
                continue
            if target not in index_by_id:
                errors.append(_error("DANGLING_LINK", path + "." + link,
                                     "step %r does not exist" % target))
                continue
            target_position = index_by_id[target]
            if target_position >= position:
                errors.append(_error("LINK_ORDER", path + "." + link,
                                     "must point to an earlier step"))
            original = steps[target_position]
            if isinstance(original, dict) and original.get("action") \
                    and original.get("action") != step.get("action"):
                errors.append(_error(
                    "ACTION_MISMATCH", path + "." + link,
                    "%s must repeat the same action (%r), not %r"
                    % (link, original.get("action"), step.get("action"))))
        if str(step.get("vendor") or "") and not str(step.get("external_id") or ""):
            errors.append(_error(
                "VENDOR_ID_MISSING", path + ".external_id",
                "a vendor record must keep the vendor-side id for reconciliation"))
    return errors


def _validate_observation_entry(entry: Dict[str, Any], path: str,
                                errors: List[Dict[str, str]]) -> None:
    if entry.get("trust") != "observed":
        errors.append(_error(
            "OBSERVATION_TRUST", path + ".trust",
            "an observation is something the collector saw; reported/derived "
            "evidence uses another kind"))
    context = entry.get("context")
    if not isinstance(context, dict):
        errors.append(_error("OBSERVATION_CONTEXT", path + ".context",
                             "product observations need a context object"))
    else:
        for field in CONTEXT_FIELDS:
            if not str(context.get(field) or "").strip():
                errors.append(_error("OBSERVATION_CONTEXT", path + ".context." + field,
                                     "product observations must record %s" % field))
    generalization = entry.get("generalization")
    if generalization not in GENERALIZATIONS:
        errors.append(_error(
            "OBSERVATION_GENERALIZATION", path + ".generalization",
            "must be one of %s; a product observation never becomes a universal "
            "capability claim" % ", ".join(GENERALIZATIONS)))
        return
    repeat = entry.get("repeat_count")
    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
        errors.append(_error("OBSERVATION_REPEAT", path + ".repeat_count",
                             "repeat_count must be an integer >= 1"))
        return
    if generalization == "single_case" and repeat != 1:
        errors.append(_error("OBSERVATION_REPEAT", path + ".repeat_count",
                             "single_case means exactly one observation"))
    if generalization == "repeated" and repeat < 2:
        errors.append(_error("OBSERVATION_REPEAT", path + ".repeat_count",
                             "repeated means at least two observations"))
    if generalization == "multi_context":
        if repeat < 2:
            errors.append(_error("OBSERVATION_REPEAT", path + ".repeat_count",
                                 "multi_context needs at least two observations"))
        contexts = entry.get("contexts")
        if not isinstance(contexts, list):
            errors.append(_error("OBSERVATION_CONTEXTS", path + ".contexts",
                                 "multi_context needs a contexts list"))
            return
        keys = set()
        for index, item in enumerate(contexts):
            if not isinstance(item, dict):
                continue
            values = tuple(str(item.get(field) or "").strip()
                           for field in CONTEXT_FIELDS)
            if all(values):
                keys.add(values)
            else:
                errors.append(_error(
                    "OBSERVATION_CONTEXTS", "%s.contexts[%d]" % (path, index),
                    "each context needs %s" % ", ".join(CONTEXT_FIELDS)))
        if len(keys) < 2:
            errors.append(_error(
                "OBSERVATION_CONTEXTS", path + ".contexts",
                "multi_context needs at least two distinct contexts"))


def validate_evidence_ledger(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "evidence")
    if doc.get("schema") != LEDGER_SCHEMA:
        return errors
    entries = doc.get("entries") or []
    _check_unique([str(item.get("evidence_id") or "") for item in entries
                   if isinstance(item, dict)], "entries.evidence_id", errors)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        path = "entries[%d]" % index
        source_hash = entry.get("source_hash")
        if isinstance(source_hash, str) and source_hash \
                and not HASH_RE.match(source_hash):
            errors.append(_error("HASH_FORMAT", path + ".source_hash",
                                 "must be sha256:<64 lowercase hex>"))
        if entry.get("kind") == "observation":
            _validate_observation_entry(entry, path, errors)
        elif entry.get("generalization") is not None:
            # Non-observation evidence may still carry a scope, but the same
            # repeat rules apply once it claims one.
            _validate_observation_entry(entry, path, errors)
    return errors


def validate_acceptance_record(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "acceptance")
    if doc.get("schema") != ACCEPTANCE_SCHEMA:
        return errors
    verdict = doc.get("verdict")
    refs = doc.get("evidence_refs") or []
    if verdict == "PASS" and not refs:
        errors.append(_error("PASS_WITHOUT_EVIDENCE", "evidence_refs",
                             "PASS must cite at least one evidence id"))
    if verdict == "FAIL" and not str(doc.get("notes") or "").strip():
        errors.append(_error("FAIL_NEEDS_NOTE", "notes",
                             "FAIL must say what failed"))
    if verdict == "NOT_APPLICABLE" and not str(doc.get("notes") or "").strip():
        errors.append(_error("NA_NEEDS_REASON", "notes",
                             "NOT_APPLICABLE must say why the criterion does not apply"))
    if len(refs) != len(set(refs)):
        errors.append(_error("DUPLICATE_REF", "evidence_refs",
                             "evidence_refs contains duplicates"))
    return errors


def validate_escalation_record(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "escalation")
    if doc.get("schema") != ESCALATION_SCHEMA:
        return errors
    if doc.get("decision") not in DECISIONS:
        errors.append(_error("ENUM", "decision",
                             "must be one of: %s" % ", ".join(DECISIONS)))
    if doc.get("decision") == "accept_with_gap" \
            and not str(doc.get("next_action") or "").strip():
        errors.append(_error("GAP_NEEDS_ACTION", "next_action",
                             "accept_with_gap still needs a tracked next action"))
    return errors


def validate_agent_e2e_run(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "agent_e2e")
    if doc.get("schema") != AGENT_E2E_SCHEMA:
        return errors
    started = _parse_instant(doc.get("started_at", ""))
    finished = _parse_instant(doc.get("finished_at", ""))
    if started and finished and finished < started:
        errors.append(_error("TIME_ORDER", "finished_at",
                             "finished_at is earlier than started_at"))
    outcome = doc.get("outcome")
    evidence = doc.get("evidence") or {}
    review = doc.get("human_review") or {}
    defects = doc.get("defect_ids") or []
    _check_unique([str(value) for value in defects], "defect_ids", errors)
    if outcome == "REAL_SUCCESS":
        if doc.get("input_class") != "real_authorized":
            errors.append(_error(
                "SYNTHETIC_NOT_REAL_SUCCESS", "input_class",
                "REAL_SUCCESS requires authorized real inputs"))
        if review.get("accepted") is not True:
            errors.append(_error(
                "SUCCESS_WITHOUT_HUMAN_ACCEPTANCE", "human_review.accepted",
                "REAL_SUCCESS requires named human acceptance"))
        if not evidence.get("deliverable_refs"):
            errors.append(_error(
                "SUCCESS_WITHOUT_DELIVERABLE", "evidence.deliverable_refs",
                "REAL_SUCCESS requires at least one final deliverable"))
        if defects:
            errors.append(_error(
                "SUCCESS_WITH_OPEN_DEFECTS", "defect_ids",
                "REAL_SUCCESS cannot carry unresolved defect ids"))
        if doc.get("product") == "growovo":
            if doc.get("external_result_observed") is not True:
                errors.append(_error(
                    "GROWOVO_EXTERNAL_RESULT_REQUIRED", "external_result_observed",
                    "Growovo REAL_SUCCESS requires an independently observed external result"))
            if not evidence.get("external_receipt_refs"):
                errors.append(_error(
                    "GROWOVO_RECEIPT_REQUIRED", "evidence.external_receipt_refs",
                    "Growovo REAL_SUCCESS requires external receipts"))
    if outcome == "JUSTIFIED_REFUSAL" and not str(doc.get("notes") or "").strip():
        errors.append(_error("REFUSAL_NEEDS_REASON", "notes",
                             "a justified refusal must explain the boundary or missing input"))
    if outcome == "HUMAN_TAKEOVER" and not review.get("minutes", 0) > 0:
        errors.append(_error("TAKEOVER_NEEDS_TIME", "human_review.minutes",
                             "human takeover must record the human time spent"))
    if outcome == "INCORRECT_DELIVERY" and not defects:
        errors.append(_error("INCORRECT_WITHOUT_DEFECT", "defect_ids",
                             "incorrect delivery must open at least one tracked defect"))
    return errors


def validate_result_receipt(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "result_receipt")
    if doc.get("schema") != RESULT_RECEIPT_SCHEMA:
        return errors
    occurred = _parse_instant(doc.get("occurred_at", ""))
    observed = _parse_instant(doc.get("observed_at", ""))
    if occurred and observed and observed < occurred:
        errors.append(_error("TIME_ORDER", "observed_at",
                             "observed_at is earlier than occurred_at"))
    if doc.get("verification_state") == "verified_business_outcome":
        review = doc.get("human_review") or {}
        if not isinstance(review, dict) or review.get("accepted") is not True:
            errors.append(_error(
                "BUSINESS_OUTCOME_WITHOUT_REVIEW", "human_review.accepted",
                "verified_business_outcome needs a named human acceptance; "
                "an observed receipt is not a business outcome"))
    return errors


def validate_delegated_task(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "delegated_task")
    if doc.get("schema") != DELEGATED_TASK_SCHEMA:
        return errors
    authorization = str(doc.get("authorization_ref") or "").strip()
    state = doc.get("state")
    if not authorization and state not in (None, "draft", "awaiting_authorization"):
        errors.append(_error(
            "AUTH_STATE_CONFLICT", "state",
            "an empty authorization_ref keeps the task in draft or "
            "awaiting_authorization, not %r" % state))
    return errors


def validate_service_capability(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "service_capability")
    if doc.get("schema") != SERVICE_CAPABILITY_SCHEMA:
        return errors
    if doc.get("maturity") == "production_proven" \
            and not doc.get("evidence_refs"):
        errors.append(_error(
            "MATURITY_WITHOUT_EVIDENCE", "evidence_refs",
            "production_proven requires evidence_refs; registration alone "
            "is not production proof"))
    return errors


def experiment_design_hash(doc: Dict[str, Any]) -> str:
    projection = {key: doc.get(key) for key in
                  ("hypothesis", "design", "window", "stop_conditions")}
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_experiment_contract(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = _schema_errors(doc, "experiment")
    if doc.get("schema") != EXPERIMENT_SCHEMA:
        return errors

    if doc.get("design_sha256") != experiment_design_hash(doc):
        errors.append(_error(
            "DESIGN_FINGERPRINT_MISMATCH", "design_sha256",
            "the fingerprint must cover hypothesis, design, window and stop_conditions"))

    window = doc.get("window") if isinstance(doc.get("window"), dict) else {}
    start = _parse_instant(str(window.get("start") or ""))
    end = _parse_instant(str(window.get("end") or ""))
    if start and end and end <= start:
        errors.append(_error("TIME_ORDER", "window.end",
                             "the experiment window must end after it starts"))
    registered_at = _parse_instant(str(doc.get("registered_at") or ""))

    design = doc.get("design") if isinstance(doc.get("design"), dict) else {}
    arms = [item for item in (design.get("arms") or []) if isinstance(item, dict)]
    metrics = [item for item in (design.get("primary_metrics") or [])
               if isinstance(item, dict)]
    arm_ids = [str(item.get("arm_id") or "") for item in arms]
    metric_ids = [str(item.get("metric_id") or "") for item in metrics]
    _check_unique(arm_ids, "design.arms.arm_id", errors)
    _check_unique(metric_ids, "design.primary_metrics.metric_id", errors)
    arm_id_set = set(arm_ids)
    metric_id_set = set(metric_ids)
    roles = {str(item.get("role") or "") for item in arms}
    experiment_type = str(design.get("experiment_type") or "")
    if experiment_type == "controlled_trial" and not {"control", "treatment"} <= roles:
        errors.append(_error(
            "CONTROL_REQUIRED", "design.arms",
            "a controlled trial needs at least one control and one treatment arm"))
    if experiment_type == "single_arm" and (len(arms) != 1 or roles != {"treatment"}):
        errors.append(_error(
            "SINGLE_ARM_CONFLICT", "design.arms",
            "a single-arm experiment needs exactly one treatment arm"))

    if doc.get("external_actions") is True and not doc.get("authorization_refs"):
        errors.append(_error(
            "EXTERNAL_ACTION_WITHOUT_AUTHORIZATION", "authorization_refs",
            "external recruitment, distribution, spend or channel actions need an authorization ref"))

    observations = [item for item in (doc.get("observations") or [])
                    if isinstance(item, dict)]
    observation_ids = [str(item.get("observation_id") or "") for item in observations]
    _check_unique(observation_ids, "observations.observation_id", errors)
    observation_by_id = {str(item.get("observation_id") or ""): item
                         for item in observations}
    eligible_primary = set()
    eligible_arms = set()
    for index, observation in enumerate(observations):
        path = "observations[%d]" % index
        arm_id = str(observation.get("arm_id") or "")
        metric_id = str(observation.get("metric_id") or "")
        if arm_id not in arm_id_set:
            errors.append(_error("UNKNOWN_ARM", path + ".arm_id",
                                 "observation references an unregistered arm"))
        if metric_id not in metric_id_set:
            errors.append(_error("UNKNOWN_METRIC", path + ".metric_id",
                                 "observation references an unregistered primary metric"))
        if observation.get("value_number") is None \
                and not str(observation.get("value_text") or "").strip():
            errors.append(_error(
                "OBSERVATION_VALUE_REQUIRED", path,
                "an observation needs value_number or value_text"))
        if observation.get("eligible") is False \
                and not str(observation.get("exclusion_reason") or "").strip():
            errors.append(_error(
                "EXCLUSION_REASON_REQUIRED", path + ".exclusion_reason",
                "an excluded observation must explain why it is ineligible"))
        observed_at = _parse_instant(str(observation.get("observed_at") or ""))
        if registered_at and observed_at and observed_at < registered_at:
            errors.append(_error(
                "OBSERVATION_BEFORE_REGISTRATION", path + ".observed_at",
                "a registered experiment cannot use observations from before registration"))
        if observed_at and ((start and observed_at < start) or (end and observed_at > end)):
            errors.append(_error(
                "OBSERVATION_OUTSIDE_WINDOW", path + ".observed_at",
                "observation time is outside the registered experiment window"))
        if observation.get("eligible") is True and metric_id in metric_id_set:
            eligible_primary.add(str(observation.get("observation_id") or ""))
            eligible_arms.add(arm_id)

    outcome = doc.get("outcome") if isinstance(doc.get("outcome"), dict) else {}
    outcome_status = str(outcome.get("status") or "")
    causality = str(outcome.get("causality") or "")
    evidence_refs = [str(value) for value in (outcome.get("evidence_refs") or [])]
    _check_unique(evidence_refs, "outcome.evidence_refs", errors)
    for ref in evidence_refs:
        if ref not in observation_by_id:
            errors.append(_error("UNKNOWN_EVIDENCE", "outcome.evidence_refs",
                                 "outcome references unknown observation %r" % ref))
    if outcome_status in ("supports_hypothesis", "refutes_hypothesis"):
        if not evidence_refs or not set(evidence_refs) & eligible_primary:
            errors.append(_error(
                "OUTCOME_WITHOUT_EVIDENCE", "outcome.evidence_refs",
                "a decisive outcome needs an eligible primary-metric observation"))
        if not str(outcome.get("evaluated_by") or "").strip() \
                or not _parse_instant(str(outcome.get("evaluated_at") or "")):
            errors.append(_error(
                "OUTCOME_REVIEW_REQUIRED", "outcome",
                "a decisive outcome needs a named evaluator and evaluation timestamp"))
    if outcome_status == "not_evaluated" and causality != "not_claimed":
        errors.append(_error(
            "OUTCOME_CAUSALITY_CONFLICT", "outcome.causality",
            "an unevaluated outcome cannot claim association or causality"))

    if causality in ("causal_supported", "causal_refuted"):
        comparability = design.get("comparability") \
            if isinstance(design.get("comparability"), dict) else {}
        comparable = all(comparability.get(field) is True for field in
                         ("same_task_set", "same_acceptance_rubric", "same_budget"))
        design_allowed = (experiment_type == "controlled_trial"
                          and design.get("assignment") == "randomized"
                          and {"control", "treatment"} <= roles
                          and comparable
                          and eligible_arms >= arm_id_set)
        if not design_allowed:
            errors.append(_error(
                "CAUSAL_DESIGN_INSUFFICIENT", "outcome.causality",
                "causal claims need randomized comparable control/treatment arms and eligible observations in every arm"))
        expected_status = ("supports_hypothesis" if causality == "causal_supported"
                           else "refutes_hypothesis")
        if outcome_status != expected_status:
            errors.append(_error(
                "CAUSAL_RESULT_MISMATCH", "outcome.status",
                "%s requires outcome status %s" % (causality, expected_status)))
    return errors


VALIDATORS = {
    "task": validate_task_contract,
    "trace": validate_execution_trace,
    "evidence": validate_evidence_ledger,
    "acceptance": validate_acceptance_record,
    "escalation": validate_escalation_record,
    "agent_e2e": validate_agent_e2e_run,
    "result_receipt": validate_result_receipt,
    "delegated_task": validate_delegated_task,
    "service_capability": validate_service_capability,
    "experiment": validate_experiment_contract,
}


def validate_document(doc: Dict[str, Any], kind: str = "") -> List[Dict[str, str]]:
    resolved = kind or detect_kind(doc)
    if not resolved:
        return [_error("UNKNOWN_SCHEMA", "schema",
                       "missing or unknown schema (expected one of %s)"
                       % ", ".join(sorted(KIND_BY_SCHEMA)))]
    if resolved not in VALIDATORS:
        return [_error("UNKNOWN_KIND", "kind",
                       "unknown kind %r (use %s)"
                       % (resolved, ", ".join(sorted(VALIDATORS))))]
    return VALIDATORS[resolved](doc)


def _context_key(entry: Dict[str, Any]) -> Tuple[str, ...]:
    context = entry.get("context") or {}
    return tuple(str(context.get(field) or "").strip() for field in CONTEXT_FIELDS)


def _matches_escalation(escalation: Dict[str, Any], record: Dict[str, Any],
                        contract_id: str) -> bool:
    if escalation.get("contract_id") != contract_id:
        return False
    target = str(escalation.get("deliverable_id") or "")
    if target and target != record.get("deliverable_id"):
        return False
    criterion = str(escalation.get("criterion") or "")
    if criterion and criterion != record.get("criterion"):
        return False
    return True


def _pick_escalation(escalations: List[Dict[str, Any]], record: Dict[str, Any],
                     contract_id: str) -> Optional[Dict[str, Any]]:
    matches = [item for item in escalations
               if _matches_escalation(item, record, contract_id)]
    if not matches:
        return None
    return max(matches, key=lambda item: str(item.get("decided_at") or ""))


def _deliverable_status(records: List[Dict[str, Any]],
                        escalations: List[Dict[str, Any]],
                        contract_id: str,
                        errors: List[Dict[str, str]],
                        deliverable_id: str) -> str:
    verdicts = {str(record.get("verdict") or "") for record in records}
    status = "ACCEPTED"
    has_gap = False
    blocked = False
    failed = False
    for record in records:
        verdict = str(record.get("verdict") or "")
        criterion = str(record.get("criterion") or "")
        if verdict == "NOT_APPLICABLE":
            continue
        if verdict == "PASS":
            continue
        escalation = _pick_escalation(escalations, record, contract_id)
        if verdict == "FAIL":
            if escalation is None:
                errors.append(_error(
                    "FAIL_WITHOUT_ESCALATION",
                    "acceptance[%s]" % record.get("acceptance_id"),
                    "FAIL on %r has no escalation record" % criterion))
                failed = True
                continue
            expected = "failed_criterion"
            if escalation.get("trigger") != expected:
                errors.append(_error(
                    "ESCALATION_TRIGGER", "escalation[%s].trigger"
                    % escalation.get("escalation_id"),
                    "a failed criterion needs trigger %r, got %r"
                    % (expected, escalation.get("trigger"))))
        elif verdict == "UNPROVEN":
            if escalation is None:
                blocked = True
                continue
            if escalation.get("trigger") not in ("unproven_evidence",
                                                 "conflicting_evidence"):
                errors.append(_error(
                    "ESCALATION_TRIGGER", "escalation[%s].trigger"
                    % escalation.get("escalation_id"),
                    "unproven evidence needs trigger unproven_evidence or "
                    "conflicting_evidence, got %r" % escalation.get("trigger")))
        decision = escalation.get("decision")
        if decision == "accept_with_gap":
            has_gap = True
        elif decision == "stop":
            failed = True
        else:
            blocked = True
    if failed:
        status = "FAILED"
    elif blocked:
        status = "BLOCKED"
    elif has_gap:
        status = "ACCEPTED_WITH_GAP"
    elif verdicts and verdicts <= {"NOT_APPLICABLE"}:
        status = "ACCEPTED"
    return status


def _worst(statuses: List[str]) -> str:
    order = ["FAILED", "BLOCKED", "ACCEPTED_WITH_GAP", "ACCEPTED"]
    for status in order:
        if status in statuses:
            return status
    return "ACCEPTED"


def time_semantics(document: Dict[str, Any]) -> Dict[str, Any]:
    uncertain = set()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = _join(path, key)
                if key.endswith("_at") and isinstance(item, str) and DATETIME_RE.match(item):
                    try:
                        parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
                    except ValueError:
                        parsed = None
                    if parsed is not None and parsed.tzinfo is None:
                        uncertain.add(child)
                walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, "%s[%d]" % (path, index) if path else "[%d]" % index)

    walk(document, "")
    return {"status": "UNCERTAIN" if uncertain else "EXPLICIT",
            "timezone_assumed": "UTC" if uncertain else None,
            "paths": sorted(uncertain)}


def validate_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    if bundle.get("schema") != BUNDLE_SCHEMA:
        errors.append(_error("UNKNOWN_SCHEMA", "schema",
                             "expected %s" % BUNDLE_SCHEMA))
    sections = {
        "task": bundle.get("task_contract"),
        "trace": bundle.get("execution_trace"),
        "evidence": bundle.get("evidence_ledger"),
    }
    for kind, doc in sections.items():
        if not isinstance(doc, dict):
            errors.append(_error("MISSING_SECTION", kind,
                                 "bundle section %r is missing" % kind))
        else:
            errors.extend(validate_document(doc, kind))
    acceptances = bundle.get("acceptances")
    escalations = bundle.get("escalations")
    if not isinstance(acceptances, list):
        errors.append(_error("MISSING_SECTION", "acceptances",
                             "bundle section 'acceptances' must be a list"))
        acceptances = []
    if not isinstance(escalations, list):
        escalations = []
    for index, doc in enumerate(acceptances):
        if not isinstance(doc, dict):
            errors.append(_error("TYPE", "acceptances[%d]" % index,
                                 "must be an object"))
            continue
        errors.extend(validate_document(doc, "acceptance"))
    for index, doc in enumerate(escalations):
        if not isinstance(doc, dict):
            errors.append(_error("TYPE", "escalations[%d]" % index,
                                 "must be an object"))
            continue
        errors.extend(validate_document(doc, "escalation"))

    contract = sections["task"] if isinstance(sections["task"], dict) else {}
    trace = sections["trace"] if isinstance(sections["trace"], dict) else {}
    ledger = sections["evidence"] if isinstance(sections["evidence"], dict) else {}
    contract_id = str(contract.get("contract_id") or "")
    trace_id = str(trace.get("trace_id") or "")

    if trace and contract and trace.get("contract_id") != contract_id:
        errors.append(_error("CONTRACT_MISMATCH", "execution_trace.contract_id",
                             "trace belongs to %r, not %r"
                             % (trace.get("contract_id"), contract_id)))
    if ledger and contract and ledger.get("contract_id") != contract_id:
        errors.append(_error("CONTRACT_MISMATCH", "evidence_ledger.contract_id",
                             "ledger belongs to %r, not %r"
                             % (ledger.get("contract_id"), contract_id)))

    deliverable_ids = [str(item.get("id") or "") for item in
                       (contract.get("deliverables") or [])
                       if isinstance(item, dict)]
    criteria_by_deliverable = {
        str(item.get("id") or ""): [str(value) for value in
                                    (item.get("acceptance_criteria") or [])]
        for item in (contract.get("deliverables") or [])
        if isinstance(item, dict)
    }
    evidence_ids = {str(item.get("evidence_id") or "") for item in
                    (ledger.get("entries") or []) if isinstance(item, dict)}

    _check_unique([str(item.get("acceptance_id") or "") for item in acceptances
                   if isinstance(item, dict)], "acceptances.acceptance_id", errors)
    _check_unique([str(item.get("escalation_id") or "") for item in escalations
                   if isinstance(item, dict)], "escalations.escalation_id", errors)

    by_deliverable: Dict[str, List[Dict[str, Any]]] = {key: [] for key in deliverable_ids}
    for record in acceptances:
        if not isinstance(record, dict):
            continue
        acceptance_id = str(record.get("acceptance_id") or "")
        deliverable_id = str(record.get("deliverable_id") or "")
        if record.get("contract_id") != contract_id:
            errors.append(_error("CONTRACT_MISMATCH",
                                 "acceptance[%s].contract_id" % acceptance_id,
                                 "record belongs to %r, not %r"
                                 % (record.get("contract_id"), contract_id)))
        if record.get("trace_id") != trace_id:
            errors.append(_error("TRACE_MISMATCH",
                                 "acceptance[%s].trace_id" % acceptance_id,
                                 "record cites trace %r, bundle has %r"
                                 % (record.get("trace_id"), trace_id)))
        if deliverable_id not in criteria_by_deliverable:
            errors.append(_error("UNKNOWN_DELIVERABLE",
                                 "acceptance[%s].deliverable_id" % acceptance_id,
                                 "%r is not in the task contract" % deliverable_id))
            continue
        if record.get("criterion") not in criteria_by_deliverable[deliverable_id]:
            errors.append(_error(
                "CRITERION_MISMATCH",
                "acceptance[%s].criterion" % acceptance_id,
                "criterion must quote one of the contract criteria for %r"
                % deliverable_id))
        for ref in record.get("evidence_refs") or []:
            if str(ref) not in evidence_ids:
                errors.append(_error("UNKNOWN_EVIDENCE",
                                     "acceptance[%s].evidence_refs" % acceptance_id,
                                     "evidence %r is not in the ledger" % ref))
        by_deliverable.setdefault(deliverable_id, []).append(record)

    for escalation in escalations:
        if not isinstance(escalation, dict):
            continue
        escalation_id = str(escalation.get("escalation_id") or "")
        if escalation.get("contract_id") != contract_id:
            errors.append(_error("CONTRACT_MISMATCH",
                                 "escalation[%s].contract_id" % escalation_id,
                                 "escalation belongs to %r, not %r"
                                 % (escalation.get("contract_id"), contract_id)))
        target = str(escalation.get("deliverable_id") or "")
        if target and target not in criteria_by_deliverable:
            errors.append(_error("UNKNOWN_DELIVERABLE",
                                 "escalation[%s].deliverable_id" % escalation_id,
                                 "%r is not in the task contract" % target))

    deliverable_results = []
    statuses = []
    for deliverable_id in deliverable_ids:
        records = by_deliverable.get(deliverable_id, [])
        if not records:
            errors.append(_error("NO_ACCEPTANCE", "deliverables.%s" % deliverable_id,
                                 "deliverable has no acceptance record"))
            status = "BLOCKED"
        else:
            status = _deliverable_status(records, escalations, contract_id,
                                         errors, deliverable_id)
        statuses.append(status)
        deliverable_results.append({
            "deliverable_id": deliverable_id,
            "status": status,
            "records": len(records),
            "verdicts": sorted({str(item.get("verdict") or "") for item in records}),
        })

    overall = _worst(statuses) if statuses else "BLOCKED"
    verdict = {
        "FAILED": "FAIL",
        "BLOCKED": "BLOCKED",
        "ACCEPTED_WITH_GAP": "PASS_WITH_GAP",
        "ACCEPTED": "PASS",
    }[overall]
    if errors:
        verdict = "INVALID" if not deliverable_results else verdict
    return {
        "schema": BUNDLE_SCHEMA,
        "contract_id": contract_id,
        "verdict": verdict,
        "deliverables": deliverable_results,
        "errors": errors,
        "ok": not errors and verdict in ("PASS", "PASS_WITH_GAP"),
    }


def observation_scope_note(entry: Dict[str, Any]) -> str:
    """Human-readable scope line for an observation entry (used by exporters)."""
    context = entry.get("context") or {}
    return "%s / %s / %s / %s · %s x%d" % (
        context.get("product_version") or "?",
        context.get("platform") or "?",
        context.get("region") or "?",
        context.get("account_permission") or "?",
        entry.get("generalization") or "?",
        int(entry.get("repeat_count") or 0),
    )


__all__ = [
    "BUNDLE_SCHEMA", "TASK_SCHEMA", "TRACE_SCHEMA", "LEDGER_SCHEMA",
    "ACCEPTANCE_SCHEMA", "ESCALATION_SCHEMA", "AGENT_E2E_SCHEMA",
    "RESULT_RECEIPT_SCHEMA", "DELEGATED_TASK_SCHEMA", "SERVICE_CAPABILITY_SCHEMA",
    "EXPERIMENT_SCHEMA",
    "KIND_BY_SCHEMA", "SCHEMA_BY_KIND",
    "VERDICTS", "DECISIONS", "TRIGGERS", "GENERALIZATIONS", "CONTEXT_FIELDS",
    "AcceptanceError", "load_json", "load_schema", "detect_kind",
    "validate_task_contract", "validate_execution_trace",
    "validate_evidence_ledger", "validate_acceptance_record",
    "validate_escalation_record", "validate_agent_e2e_run",
    "validate_result_receipt", "validate_delegated_task",
    "validate_service_capability", "experiment_design_hash",
    "validate_experiment_contract",
    "validate_document", "validate_bundle",
    "observation_scope_note",
]
