"""Machine-readable business-scenario entry, evidence and acceptance coverage."""
from __future__ import annotations

import re
from collections import Counter

SCHEMA = "ovo.business-scenario-catalog/1"
PRODUCTS = {"A": "askovo", "G": "growovo", "V": "verovo"}
IMPLEMENTATION = {"local", "partial", "unknown", "not_implemented"}
ACCEPTANCE = {"not_run", "synthetic_passed", "real_partial", "accepted_real", "accepted_external"}
ACCEPTED = {"accepted_real", "accepted_external"}


def summarize(document):
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("scenario catalog schema must be %s" % SCHEMA)
    if not str(document.get("catalog_id") or "").strip() or not str(document.get("source_ref") or "").strip():
        raise ValueError("catalog_id and source_ref are required")
    rows = document.get("scenarios")
    if not isinstance(rows, list) or not rows:
        raise ValueError("scenarios must be a non-empty array")
    seen = set()
    by_product = Counter()
    implementation = Counter()
    acceptance = Counter()
    for index, row in enumerate(rows):
        label = "scenarios[%d]" % index
        if not isinstance(row, dict):
            raise ValueError(label + " must be an object")
        scenario_id = str(row.get("scenario_id") or "")
        if not re.fullmatch(r"[AGV]-S[0-9]{2}", scenario_id):
            raise ValueError(label + " has an invalid scenario_id")
        if scenario_id in seen:
            raise ValueError("duplicate scenario_id: %s" % scenario_id)
        seen.add(scenario_id)
        product = PRODUCTS[scenario_id[0]]
        if row.get("product") != product:
            raise ValueError("%s product must be %s" % (scenario_id, product))
        if not str(row.get("title") or "").strip():
            raise ValueError("%s title is required" % scenario_id)
        entrypoints = row.get("entrypoints")
        if not isinstance(entrypoints, list) or not entrypoints \
                or not all(str(value or "").strip() for value in entrypoints):
            raise ValueError("%s needs at least one entrypoint" % scenario_id)
        for key in ("existing_evidence", "test_refs", "case_refs", "missing"):
            if not isinstance(row.get(key), list):
                raise ValueError("%s.%s must be an array" % (scenario_id, key))
        implementation_status = row.get("implementation_status")
        acceptance_status = row.get("acceptance_status")
        if implementation_status not in IMPLEMENTATION:
            raise ValueError("%s has an unknown implementation_status" % scenario_id)
        if acceptance_status not in ACCEPTANCE:
            raise ValueError("%s has an unknown acceptance_status" % scenario_id)
        if acceptance_status in ACCEPTED and row["missing"]:
            raise ValueError("%s accepted status cannot retain missing conditions" % scenario_id)
        if acceptance_status in ACCEPTED and not row["case_refs"]:
            raise ValueError("%s accepted status needs case_refs" % scenario_id)
        by_product[product] += 1
        implementation[implementation_status] += 1
        acceptance[acceptance_status] += 1
    accepted = sum(acceptance[status] for status in ACCEPTED)
    return {
        "schema": "ovo.business-scenario-coverage/1",
        "catalog_id": document["catalog_id"],
        "source_ref": document["source_ref"],
        "coverage": {
            "total": len(rows),
            "by_product": {product: by_product[product] for product in ("askovo", "growovo", "verovo")},
            "implementation": dict(sorted(implementation.items())),
            "acceptance": dict(sorted(acceptance.items())),
            "accepted_real": acceptance["accepted_real"],
            "accepted_external": acceptance["accepted_external"],
            "not_accepted": len(rows) - accepted,
            "all_scenarios_have_entrypoints": True,
        },
        "boundary": "Entrypoints, local implementation and synthetic evidence are not product completion. Acceptance remains scoped to the cited cases; unlisted real inputs, human acceptance and external reuse stay unproven.",
    }
