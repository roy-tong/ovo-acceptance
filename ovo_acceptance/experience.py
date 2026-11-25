"""Low-touch accepted-delivery rate and Experience Failure Taxonomy."""
from __future__ import annotations

from typing import Any, Dict

from . import model

SCHEMA = "ovo.experience-summary/1"
CATEGORIES = (
    "discovery_failure", "installation_failure", "invocation_failure",
    "context_failure", "data_failure", "execution_failure", "recovery_failure",
    "intelligence_failure", "delivery_failure", "intervention_failure", "value_failure",
)
EFFORT_FIELDS = ("total_minutes", "authorization_minutes",
                 "business_input_minutes", "product_issue_minutes")


def _minutes(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError("%s must be a non-negative number" % label)
    return value


def summarize(document):
    if not isinstance(document, dict) or not isinstance(document.get("runs"), list):
        raise ValueError("experience input needs a runs array")
    runs = document["runs"]
    by_id = {}
    for run in runs:
        errors = model.validate_document(run, "agent_e2e")
        if errors:
            raise ValueError("invalid agent-e2e run %s: %s" % (
                run.get("run_id"), errors[0].get("message")))
        run_id = str(run["run_id"])
        if run_id in by_id:
            raise ValueError("duplicate run_id %s" % run_id)
        by_id[run_id] = run
    effort = document.get("effort") or {}
    limits = document.get("human_limits") or {}
    if not isinstance(effort, dict) or not isinstance(limits, dict):
        raise ValueError("effort and human_limits must be objects")
    for run_id, row in effort.items():
        if run_id not in by_id or not isinstance(row, dict):
            raise ValueError("effort references an unknown run")
        for field in EFFORT_FIELDS:
            _minutes(row.get(field), "effort.%s.%s" % (run_id, field))
        if row["total_minutes"] < sum(row[field] for field in EFFORT_FIELDS[1:]):
            raise ValueError("effort total_minutes is smaller than its components")
    for case_id, value in limits.items():
        _minutes(value, "human_limits.%s" % case_id)

    real = [run for run in runs if run.get("input_class") == "real_authorized"]
    real_ids = {run["run_id"] for run in real}
    taxonomy = {category: 0 for category in CATEGORIES}
    failures = document.get("failures") or []
    if not isinstance(failures, list):
        raise ValueError("failures must be an array")
    for failure in failures:
        if not isinstance(failure, dict) or failure.get("category") not in CATEGORIES:
            raise ValueError("failure category is not registered")
        run_id = str(failure.get("run_id") or "")
        if run_id not in by_id:
            raise ValueError("failure references an unknown run")
        if run_id in real_ids:
            taxonomy[failure["category"]] += 1

    outcome_counts = {}
    per_case = {}
    missing_effort = 0
    missing_limit = 0
    high_touch_success = 0
    numerator = 0
    effort_totals = {field: 0 for field in EFFORT_FIELDS}
    for run in real:
        outcome_counts[run["outcome"]] = outcome_counts.get(run["outcome"], 0) + 1
        case_id = run["case_id"]
        case = per_case.setdefault(case_id, {"eligible_started": 0, "accepted_low_touch": 0})
        case["eligible_started"] += 1
        run_id = run["run_id"]
        row = effort.get(run_id)
        if row is None:
            missing_effort += 1
        else:
            for field in EFFORT_FIELDS:
                effort_totals[field] += row[field]
        limit = limits.get(case_id)
        if limit is None:
            missing_limit += 1
        low_touch = (run["outcome"] == "REAL_SUCCESS" and row is not None
                     and limit is not None and row["total_minutes"] <= limit)
        if low_touch:
            numerator += 1
            case["accepted_low_touch"] += 1
        elif run["outcome"] == "REAL_SUCCESS":
            high_touch_success += 1
    for case in per_case.values():
        case["low_touch_accepted_delivery_rate"] = (
            round(case["accepted_low_touch"] / case["eligible_started"], 6)
            if case["eligible_started"] else None)
    return {
        "schema": SCHEMA,
        "scope": "real_authorized_started_runs",
        "eligible_started": len(real),
        "accepted_low_touch": numerator,
        "low_touch_accepted_delivery_rate": round(numerator / len(real), 6) if real else None,
        "formula": "accepted low-touch real-authorized runs / all started real-authorized runs",
        "outcomes": outcome_counts,
        "cases": per_case,
        "non_real_observations": len(runs) - len(real),
        "coverage": {
            "missing_effort": missing_effort,
            "missing_human_limit": missing_limit,
            "high_touch_or_unmeasured_success": high_touch_success,
        },
        "human_effort_minutes": effort_totals,
        "failure_taxonomy": taxonomy,
        "boundary": "Human-effort records are separate observations. Synthetic runs, missing effort and missing limits never become zero-touch successes; the rate is descriptive, not causal.",
    }
