"""Read-only C-01 adapters over existing proof bundles and product boundaries.

These adapters do not run a product and do not upgrade a proof into a business
outcome. They turn an existing, already-validated Proof Bundle into an
``ovo.result-receipt/1`` projection, and publish a static
``ovo.service-capability/1`` descriptor for each product. A receipt created
here is ``verification_state=observed`` and ``causality=not_claimed``: it says
"this bundle was validated", not "the business succeeded".
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from . import model, proof


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def receipt_from_proof_bundle(path: str | Path, *, reviewed_by: str = "",
                              observed_at: str = "") -> Dict[str, Any]:
    root = Path(path)
    proof_doc = model.load_json(root / "proof.json")
    contract = model.load_json(root / "contract.json")
    result = proof.validate_proof_bundle(root)
    if result.get("errors"):
        raise ValueError("proof bundle is invalid: %s" % "; ".join(
            "%s:%s" % (item.get("code"), item.get("path"))
            for item in result["errors"][:5]))

    generated_at = str(proof_doc.get("generated_at") or "") or _now()
    product = str(proof_doc.get("product") or "family")
    if product not in ("askovo", "growovo", "verovo", "family"):
        product = "family"
    source_hash = "sha256:" + hashlib.sha256(
        (root / "proof.json").read_bytes()).hexdigest()
    contract_id = str(contract.get("contract_id") or "unknown")
    proof_id = str(proof_doc.get("proof_id") or "unknown")
    receipt = {
        "schema": "ovo.result-receipt/1",
        "receipt_id": "rr-%s" % proof_id,
        "origin_product": product,
        "origin_version": str(
            (proof_doc.get("environment") or {}).get("product_version") or "unknown"),
        "task_id": contract_id,
        "run_id": proof_id,
        "subject_id": str(contract.get("owner") or contract_id),
        "event_type": "proof_bundle_validated",
        "occurred_at": generated_at,
        "observed_at": observed_at or generated_at,
        "source_ref": "proof.json",
        "source_hash": source_hash,
        "assertion": "Proof bundle %s validated with status %s." % (
            proof_id, result.get("status")),
        "qualification": {
            "proof_status": result.get("status"),
            "acceptance_verdict": result.get("acceptance_verdict"),
            "counts_by_status": result.get("counts_by_status"),
        },
        "verification_state": "observed",
        "human_review": ({"reviewed_by": reviewed_by} if reviewed_by else {}),
        "scope": {"workspace_id": "proof-bundle", "product": product},
        "causality": "not_claimed",
        "notes": "Read-only projection; a validated bundle is not a business outcome.",
    }
    errors = model.validate_document(receipt)
    if errors:
        raise ValueError("receipt is invalid: %s" % "; ".join(
            "%s:%s" % (item.get("code"), item.get("path")) for item in errors))
    return receipt


CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "askovo": {
        "schema": "ovo.service-capability/1",
        "service": "askovo.research",
        "use_case": "Run one product-decision research task and produce a Decision Brief and Proof Bundle.",
        "supported_inputs": ["product decision question", "authorized research materials",
                             "study workspace"],
        "outputs": ["Decision Brief", "seven-node product reasoning", "Proof Bundle"],
        "side_effect_level": "read_external",
        "requires_human_approval": ["live collection authorization", "semantic review",
                                    "final product/business decision"],
        "can_resume": True,
        "refusal_examples": [
            "No authorized source: report a research gap; never switch to a commercial provider.",
            "No quotable evidence: keep the claim unverified.",
        ],
        "maturity": "offline_verified",
        "notes": "Static product-boundary descriptor; not a live capability probe.",
    },
    "growovo": {
        "schema": "ovo.service-capability/1",
        "service": "growovo.growth-operator",
        "use_case": "Run one authorized campaign batch, execute approved actions, read back receipts and surface reply follow-ups.",
        "supported_inputs": ["goal contract", "authorized account reference", "approved queue"],
        "outputs": ["operations ledger", "readback receipts", "daily result card"],
        "side_effect_level": "write_external",
        "requires_human_approval": ["arm run", "policy change", "DNC change", "payment"],
        "can_resume": True,
        "refusal_examples": [
            "Unauthorized account: refuse before dispatch.",
            "Unknown external result: stop, reconcile, never auto-retry.",
        ],
        "maturity": "offline_verified",
        "notes": "Static product-boundary descriptor; not a live capability probe.",
    },
    "verovo": {
        "schema": "ovo.service-capability/1",
        "service": "verovo.buyer-verification",
        "use_case": "Review one AI supplier billing period and keep charges, delivery and evidence coverage separate.",
        "supported_inputs": ["local invoice/usage exports", "buyer criteria",
                             "period rule mapping"],
        "outputs": ["close report", "spend-action list", "Proof Bundle"],
        "side_effect_level": "none",
        "requires_human_approval": ["rule mapping", "signoff", "delivery acceptance",
                                    "buyer decision"],
        "can_resume": True,
        "refusal_examples": [
            "Missing evidence: return UNPROVABLE; never fill the gap.",
            "Partial or lossy window: abstain instead of claiming a result.",
        ],
        "maturity": "offline_verified",
        "notes": "Static product-boundary descriptor; not a live capability probe.",
    },
}


def capability_descriptor(product: str) -> Dict[str, Any]:
    key = str(product or "").strip().lower()
    if key not in CAPABILITIES:
        raise ValueError("unknown product: %s (use askovo, growovo or verovo)" % product)
    descriptor = dict(CAPABILITIES[key])
    errors = model.validate_document(descriptor)
    if errors:
        raise ValueError("capability is invalid: %s" % "; ".join(
            "%s:%s" % (item.get("code"), item.get("path")) for item in errors))
    return descriptor


__all__ = ["receipt_from_proof_bundle", "capability_descriptor", "CAPABILITIES"]
