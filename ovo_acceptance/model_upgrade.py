"""Four-arm Model Upgrade Test comparison with explicit comparability limits."""
from __future__ import annotations

import copy
from typing import Any, Dict

SCHEMA = "ovo.model-upgrade-test/1"
RESULT_SCHEMA = "ovo.model-upgrade-result/1"
ARM_NAMES = ("weak_without_product", "weak_with_product",
             "strong_without_product", "strong_with_product")
COMPARABILITY = ("same_task", "same_inputs", "same_authorization",
                 "same_acceptance_rubric", "same_budget")


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a finite number" % label)
    return value


def _validate(doc):
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError("model upgrade schema must be %s" % SCHEMA)
    for key in ("test_id", "task_id", "input_class", "product", "metric", "comparability", "arms"):
        if not doc.get(key):
            raise ValueError("model upgrade.%s is required" % key)
    if not str(doc.get("weak_model") or "").strip() \
            or not str(doc.get("strong_model") or "").strip() \
            or doc["weak_model"] == doc["strong_model"]:
        raise ValueError("weak_model and strong_model must be distinct")
    metric = doc["metric"]
    for key in ("metric_id", "definition", "unit", "direction"):
        if not metric.get(key):
            raise ValueError("metric.%s is required" % key)
    if metric["direction"] not in ("higher_better", "lower_better"):
        raise ValueError("metric.direction must be higher_better or lower_better")
    tolerance = _number(metric.get("tolerance", 0), "metric.tolerance")
    if tolerance < 0:
        raise ValueError("metric.tolerance must be non-negative")
    arms = doc["arms"]
    if set(arms) != set(ARM_NAMES):
        raise ValueError("arms must contain exactly the four registered arms")
    refs = []
    for name in ARM_NAMES:
        arm = arms[name]
        if not isinstance(arm, dict) or not str(arm.get("run_ref") or "").strip():
            raise ValueError("%s.run_ref is required" % name)
        if not str(arm.get("evidence_ref") or "").strip():
            raise ValueError("%s.evidence_ref is required" % name)
        _number(arm.get("value"), name + ".value")
        refs.append(arm["run_ref"])
    if len(set(refs)) != 4:
        raise ValueError("the four arms must use unique fresh run refs")


def compare(doc):
    _validate(doc)
    comparability = doc["comparability"]
    reasons = [key for key in COMPARABILITY if comparability.get(key) is not True]
    for name in ARM_NAMES:
        arm = doc["arms"][name]
        if arm.get("accepted") is not True:
            reasons.append(name + ".not_accepted")
        if arm.get("fresh_session") is not True:
            reasons.append(name + ".not_fresh")
        if arm.get("natural_language_task") is not True:
            reasons.append(name + ".not_natural_language")
        if arm.get("solution_hints_provided") is not False:
            reasons.append(name + ".solution_hints")
    eligible = not reasons
    if not eligible:
        return {
            "schema": RESULT_SCHEMA,
            "test_id": doc["test_id"],
            "status": "INELIGIBLE",
            "classification": "not_assessed",
            "reason_codes": reasons,
            "gains": None,
            "causality": "not_claimed",
            "evidence_strength": "single_task_descriptive",
        }
    sign = 1 if doc["metric"]["direction"] == "higher_better" else -1
    arms = doc["arms"]
    weak_gain = sign * (arms["weak_with_product"]["value"] - arms["weak_without_product"]["value"])
    strong_gain = sign * (arms["strong_with_product"]["value"] - arms["strong_without_product"]["value"])
    amplification = strong_gain - weak_gain
    tolerance = doc["metric"].get("tolerance", 0)
    if amplification > tolerance:
        classification = "amplified"
    elif amplification < -tolerance:
        classification = "diminishing"
    else:
        classification = "stable"
    return {
        "schema": RESULT_SCHEMA,
        "test_id": doc["test_id"],
        "task_id": doc["task_id"],
        "status": "ELIGIBLE",
        "input_class": doc["input_class"],
        "product": copy.deepcopy(doc["product"]),
        "weak_model": doc["weak_model"],
        "strong_model": doc["strong_model"],
        "metric": copy.deepcopy(doc["metric"]),
        "classification": classification,
        "reason_codes": [],
        "gains": {
            "product_with_weak_model": weak_gain,
            "product_with_strong_model": strong_gain,
            "amplification": amplification,
            "model_without_product": sign * (
                arms["strong_without_product"]["value"] - arms["weak_without_product"]["value"]),
            "model_with_product": sign * (
                arms["strong_with_product"]["value"] - arms["weak_with_product"]["value"]),
        },
        "run_refs": {name: {"run_ref": arms[name]["run_ref"],
                            "evidence_ref": arms[name]["evidence_ref"]} for name in ARM_NAMES},
        "causality": "not_claimed",
        "evidence_strength": "single_task_descriptive",
        "boundary": "One comparable task does not establish a general product architecture verdict, causal effect or performance on larger/longer tasks.",
    }
