"""Machine-readable roadmap work-item implementation, scope and acceptance coverage."""
from __future__ import annotations

import re
from collections import Counter

SCHEMA = "ovo.roadmap-work-items/1"
PRODUCTS = {"A": "askovo", "G": "growovo", "V": "verovo"}
IMPLEMENTATION = {"local", "partial", "unknown", "not_implemented", "external_only", "not_applicable"}
ACCEPTANCE = {"not_run", "synthetic_passed", "real_partial", "accepted_real", "accepted_external", "not_applicable"}
SCOPE_STATUSES = {"not_needed", "pending", "accepted", "rejected"}


def summarize(document):
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("roadmap schema must be %s" % SCHEMA)
    if not str(document.get("roadmap_id") or "").strip() or not str(document.get("source_ref") or "").strip():
        raise ValueError("roadmap_id and source_ref are required")
    modules = document.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("modules must be a non-empty array")
    seen = set()
    by_product = Counter()
    implementation = Counter()
    acceptance = Counter()
    priorities = Counter()
    scope = Counter()
    unnumbered = 0
    for module in modules:
        if not isinstance(module, dict):
            raise ValueError("module must be an object")
        module_id = str(module.get("module_id") or "")
        if not re.fullmatch(r"[AGV][0-9]+", module_id):
            raise ValueError("invalid module_id")
        product = PRODUCTS[module_id[0]]
        if module.get("product") != product:
            raise ValueError("%s product must be %s" % (module_id, product))
        if not str(module.get("title") or "").strip():
            raise ValueError("%s title is required" % module_id)
        extra = module.get("unnumbered_requirements") or []
        if not isinstance(extra, list):
            raise ValueError("%s unnumbered_requirements must be an array" % module_id)
        unnumbered += bool(extra)
        items = module.get("items")
        if not isinstance(items, list):
            raise ValueError("%s items must be an array" % module_id)
        for row in items:
            if not isinstance(row, dict):
                raise ValueError("%s contains a non-object item" % module_id)
            item_id = str(row.get("item_id") or "")
            if not re.fullmatch(re.escape(module_id) + r"-[0-9]{2}", item_id):
                raise ValueError("invalid item_id for %s" % module_id)
            if item_id in seen:
                raise ValueError("duplicate item_id: %s" % item_id)
            seen.add(item_id)
            if not str(row.get("title") or "").strip():
                raise ValueError("%s title is required" % item_id)
            priority = str(row.get("priority") or "")
            if priority not in {"P0", "P1", "P2", "unknown"}:
                raise ValueError("%s priority must be P0/P1/P2 or unknown" % item_id)
            impl = row.get("implementation_status")
            acc = row.get("acceptance_status")
            if impl not in IMPLEMENTATION or acc not in ACCEPTANCE:
                raise ValueError("%s has an unknown implementation/acceptance status" % item_id)
            for key in ("evidence_refs", "test_refs", "case_refs", "unresolved"):
                if not isinstance(row.get(key), list):
                    raise ValueError("%s.%s must be an array" % (item_id, key))
            decision = row.get("scope_decision")
            if not isinstance(decision, dict) or decision.get("status") not in SCOPE_STATUSES \
                    or not str(decision.get("rationale") or "").strip():
                raise ValueError("%s scope_decision needs a status and rationale" % item_id)
            if acc == "accepted_external" and (row["unresolved"] or not row["case_refs"]):
                raise ValueError("%s external acceptance needs cases and no unresolved conditions" % item_id)
            by_product[product] += 1
            implementation[impl] += 1
            acceptance[acc] += 1
            priorities[priority] += 1
            scope[decision["status"]] += 1
    total = len(seen)
    return {
        "schema": "ovo.roadmap-coverage/1", "roadmap_id": document["roadmap_id"],
        "source_ref": document["source_ref"],
        "coverage": {
            "total": total, "modules": len(modules), "unnumbered_modules": unnumbered,
            "by_product": {product: by_product[product] for product in ("askovo", "growovo", "verovo")},
            "implementation": dict(sorted(implementation.items())),
            "acceptance": dict(sorted(acceptance.items())), "priorities": dict(sorted(priorities.items())),
            "scope_decisions": dict(sorted(scope.items())),
            "pending_scope_decisions": scope["pending"],
            "accepted_external": acceptance["accepted_external"],
            "not_accepted_external": total - acceptance["accepted_external"],
        },
        "boundary": "Implementation labels, local tests and accepted scope decisions are not external product completion. Unknown items stay unresolved; accepted_external requires case evidence and no open conditions.",
    }
