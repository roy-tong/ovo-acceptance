"""Local-only inventory of validated shared Experiment Contracts."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import model

SCHEMA = "ovo.experiment-dataset/1"


def _counts(values):
    result = {}
    for value in values:
        key = str(value or "unknown")
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def build(documents, *, dataset_id):
    if not str(dataset_id or "").strip():
        raise ValueError("dataset_id is required")
    if not isinstance(documents, list) or not documents:
        raise ValueError("experiment dataset needs at least one contract")
    experiments = []
    seen = set()
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("experiment contract must be an object")
        errors = model.validate_document(document, "experiment")
        if errors:
            first = errors[0]
            raise ValueError("invalid experiment %s: %s: %s" % (
                document.get("experiment_id"), first.get("code"), first.get("message")))
        key = (document["origin_product"], document["experiment_id"])
        if key in seen:
            raise ValueError("duplicate origin experiment: %s/%s" % key)
        seen.add(key)
        experiments.append(copy.deepcopy(document))
    experiments.sort(key=lambda row: (row["origin_product"], row["experiment_id"]))
    observations = [observation for experiment in experiments
                    for observation in experiment.get("observations") or []]
    canonical = json.dumps(experiments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema": SCHEMA,
        "dataset_id": dataset_id,
        "classification": "local_only",
        "public_release": "not_authorized",
        "analysis": "descriptive_inventory_only",
        "experiments": experiments,
        "summary": {
            "experiments": len(experiments),
            "products": _counts(row["origin_product"] for row in experiments),
            "states": _counts(row["state"] for row in experiments),
            "outcomes": _counts((row.get("outcome") or {}).get("status") for row in experiments),
            "causality": _counts((row.get("outcome") or {}).get("causality") for row in experiments),
            "observations": len(observations),
            "eligible_observations": sum(row.get("eligible") is True for row in observations),
            "excluded_observations": sum(row.get("eligible") is False for row in observations),
            "evidence_grades": _counts(row.get("evidence_grade") for row in observations),
            "external_action_experiments": sum(row.get("external_actions") is True for row in experiments),
            "metric_ids": sorted({observation.get("metric_id") for observation in observations
                                  if observation.get("metric_id")}),
        },
        "source_evidence_files_copied": False,
        "cross_experiment_pooling": "not_performed",
        "causal_upgrade": "not_performed",
        "dataset_sha256": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "boundary": "A local inventory of validated contracts, not an open-data release. Source files are not copied; heterogeneous metrics and populations are not pooled. Public sharing requires separate authorization and redaction.",
    }


def write_new(document, out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError("experiment dataset output must be new or empty: %s" % out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "dataset.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target
