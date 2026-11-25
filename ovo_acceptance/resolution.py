"""Shared Problem Resolution Contract with fail-safe next-action semantics."""
from __future__ import annotations

import copy

SCHEMA = "ovo.problem-resolution/1"
RESULT_SCHEMA = "ovo.problem-resolution-result/1"
PRODUCTS = ("askovo", "growovo", "verovo")
RESOLUTIONS = ("auto_fix", "switch_path", "partial_delivery", "data_needed",
               "permission_needed", "business_decision", "stop")
EFFECTS = ("none", "confirmed_no_effect", "confirmed_complete", "unknown")


def _object(document, key):
    value = document.get(key)
    if not isinstance(value, dict):
        raise ValueError("%s must be an object" % key)
    return value


def _list(value, label, minimum=1):
    if not isinstance(value, list) or len(value) < minimum or any(not str(item or "").strip() for item in value):
        raise ValueError("%s must contain at least %d non-empty item(s)" % (label, minimum))
    return value


def _true(value, label):
    if value is not True:
        raise ValueError("%s must be true" % label)


def _validate(document):
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("problem resolution schema must be %s" % SCHEMA)
    for key in ("problem_id", "task_id", "observed_at", "requested_resolution"):
        if not str(document.get(key) or "").strip():
            raise ValueError("problem resolution.%s is required" % key)
    if document.get("product") not in PRODUCTS:
        raise ValueError("product must be askovo, growovo or verovo")
    kind = document["requested_resolution"]
    if kind not in RESOLUTIONS:
        raise ValueError("requested_resolution is not registered")
    observation = _object(document, "observation")
    for key in ("code", "summary", "external_effect_status"):
        if not str(observation.get(key) or "").strip():
            raise ValueError("observation.%s is required" % key)
    if observation["external_effect_status"] not in EFFECTS:
        raise ValueError("observation.external_effect_status is not registered")
    _list(observation.get("evidence_refs"), "observation.evidence_refs")

    if kind == "auto_fix":
        fix = _object(document, "fix")
        if not str(fix.get("action_id") or "").strip():
            raise ValueError("fix.action_id is required")
        _true(fix.get("side_effect_free"), "fix.side_effect_free")
        _true(fix.get("same_authorization"), "fix.same_authorization")
        attempts = fix.get("max_attempts")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10:
            raise ValueError("fix.max_attempts must be an integer from 1 to 10")
    elif kind == "switch_path":
        alternative = _object(document, "alternative")
        if not str(alternative.get("path_id") or "").strip():
            raise ValueError("alternative.path_id is required")
        for key in ("verified", "compliant", "same_scope"):
            _true(alternative.get(key), "alternative." + key)
        _list(alternative.get("authorization_refs"), "alternative.authorization_refs")
    elif kind == "partial_delivery":
        partial = _object(document, "partial")
        _list(partial.get("deliverable_refs"), "partial.deliverable_refs")
        _list(partial.get("limitations"), "partial.limitations")
        if partial.get("completion_claim") != "partial":
            raise ValueError("partial.completion_claim must be partial")
    elif kind == "data_needed":
        data = _object(document, "data")
        for key in ("request_id", "source", "access_basis"):
            if not str(data.get(key) or "").strip():
                raise ValueError("data.%s is required" % key)
        if not isinstance(data.get("automatic_fetch_attempted"), bool):
            raise ValueError("data.automatic_fetch_attempted must be boolean")
        _true(data.get("side_effect_free_fetch"), "data.side_effect_free_fetch")
    elif kind == "permission_needed":
        permission = _object(document, "permission")
        if not str(permission.get("request_id") or "").strip():
            raise ValueError("permission.request_id is required")
        _list(permission.get("scopes"), "permission.scopes")
        _true(permission.get("incremental"), "permission.incremental")
        _true(permission.get("missing_only"), "permission.missing_only")
    elif kind == "business_decision":
        decision = _object(document, "decision")
        _list(decision.get("evidence_refs"), "decision.evidence_refs")
        options = decision.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError("decision.options must contain at least two options")
        for option in options:
            if not isinstance(option, dict) or not str(option.get("option_id") or "").strip() \
                    or not str(option.get("impact") or "").strip():
                raise ValueError("each decision option needs option_id and impact")
    else:
        stop = _object(document, "stop")
        if not str(stop.get("reason") or "").strip():
            raise ValueError("stop.reason is required")
        _true(stop.get("preserve_state"), "stop.preserve_state")


def evaluate(document):
    _validate(document)
    kind = document["requested_resolution"]
    effect = document["observation"]["external_effect_status"]
    base = {
        "schema": RESULT_SCHEMA,
        "problem_id": document["problem_id"],
        "product": document["product"],
        "task_id": document["task_id"],
        "resolution": kind,
        "execution_applied": False,
        "external_effect_status": effect,
    }
    if kind in ("auto_fix", "switch_path") and effect == "unknown":
        return dict(base, status="RECONCILE_REQUIRED", next_action="reconcile_external_result",
                    automatic_action_allowed=False, user_prompt_required=False,
                    reason_codes=["EXTERNAL_EFFECT_UNKNOWN"], action={},
                    boundary="Inspect independent receipts before retrying or switching execution paths.")
    if kind in ("auto_fix", "switch_path") and effect == "confirmed_complete":
        return dict(base, status="NO_ACTION", next_action="preserve_completed_result",
                    automatic_action_allowed=False, user_prompt_required=False,
                    reason_codes=["EXTERNAL_RESULT_ALREADY_COMPLETE"], action={},
                    boundary="A confirmed external result must not be repeated.")

    status = "READY"
    prompt = False
    automatic = False
    reasons = []
    if kind == "auto_fix":
        next_action = "apply_local_fix"
        action = document["fix"]
        automatic = True
    elif kind == "switch_path":
        next_action = "execute_alternative_path"
        action = document["alternative"]
        automatic = True
    elif kind == "partial_delivery":
        next_action = "deliver_partial"
        action = document["partial"]
    elif kind == "data_needed":
        action = document["data"]
        if action["automatic_fetch_attempted"]:
            status = "NEEDS_USER_INPUT"
            next_action = "request_data"
            prompt = True
        else:
            next_action = "fetch_data"
            automatic = True
    elif kind == "permission_needed":
        status = "NEEDS_USER_INPUT"
        next_action = "request_permission"
        action = document["permission"]
        prompt = True
    elif kind == "business_decision":
        status = "NEEDS_USER_INPUT"
        next_action = "request_business_decision"
        action = document["decision"]
        prompt = True
    else:
        next_action = "pause_related_actions"
        action = document["stop"]
        prompt = True
        reasons.append("SAFE_CONTINUATION_UNAVAILABLE")
    return dict(
        base, status=status, next_action=next_action,
        automatic_action_allowed=automatic, user_prompt_required=prompt,
        reason_codes=reasons, action=copy.deepcopy(action),
        boundary="A validated next-action proposal only. No fix, path switch, delivery, fetch, permission change, business decision or pause was applied by this evaluator.",
    )
