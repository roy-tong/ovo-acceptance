"""Validate the declared family vocabulary map.

The map is documentation plus a checkable table, not a runtime replacement for
any product's state machine. It exists so a family reviewer can translate
Askovo, Growovo and Verovo states without inventing a second truth.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

VOCABULARY_SCHEMA = "ovo.family-vocabulary/1"
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "family-vocabulary.json"


def load_vocabulary(path: str | Path | None = None) -> Dict[str, Any]:
    target = Path(path) if path else DEFAULT_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def validate_vocabulary(doc: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if doc.get("schema") != VOCABULARY_SCHEMA:
        errors.append("schema must be %s" % VOCABULARY_SCHEMA)

    identifiers = doc.get("product_identifiers")
    if not isinstance(identifiers, dict) or not identifiers:
        errors.append("product_identifiers must be a non-empty object")
        identifiers = {}
    for key in ("askovo", "growovo", "verovo", "family"):
        entry = identifiers.get(key)
        if not isinstance(entry, dict):
            errors.append("product_identifiers.%s is missing" % key)
            continue
        display = entry.get("display")
        aliases = entry.get("aliases")
        if not isinstance(display, str) or not display.strip():
            errors.append("product_identifiers.%s.display must be non-empty" % key)
        if not isinstance(aliases, list) or display not in aliases:
            errors.append("product_identifiers.%s.aliases must include display" % key)

    lifecycle = doc.get("lifecycle") or {}
    canonical = lifecycle.get("canonical")
    if not isinstance(canonical, list) or not canonical:
        errors.append("lifecycle.canonical must be a non-empty array")
        canonical = []
    canonical_set = set(canonical)
    products = lifecycle.get("products")
    if not isinstance(products, dict) or not products:
        errors.append("lifecycle.products must be a non-empty object")
        products = {}
    for product, mapping in products.items():
        if not isinstance(mapping, dict) or not mapping:
            errors.append("lifecycle.products.%s must be a non-empty object" % product)
            continue
        for internal, target in mapping.items():
            if target not in canonical_set:
                errors.append(
                    "lifecycle.products.%s.%s maps to unknown canonical state %r"
                    % (product, internal, target))

    verdicts = doc.get("verdicts") or {}
    canonical_verdicts = verdicts.get("canonical")
    if not isinstance(canonical_verdicts, list) or not canonical_verdicts:
        errors.append("verdicts.canonical must be a non-empty array")
        canonical_verdicts = []
    verdict_set = set(canonical_verdicts)
    sources = verdicts.get("sources")
    if not isinstance(sources, dict) or not sources:
        errors.append("verdicts.sources must be a non-empty object")
        sources = {}
    for source, mapping in sources.items():
        if not isinstance(mapping, dict) or not mapping:
            errors.append("verdicts.sources.%s must be a non-empty object" % source)
            continue
        for internal, target in mapping.items():
            if target not in verdict_set:
                errors.append(
                    "verdicts.sources.%s.%s maps to unknown canonical verdict %r"
                    % (source, internal, target))

    for section in ("evidence", "layers", "namespaces"):
        value = doc.get(section)
        if not isinstance(value, dict) or not value:
            errors.append("%s must be a non-empty object" % section)
    return errors


def translate_state(product: str, internal: str,
                    doc: Dict[str, Any] | None = None) -> str:
    vocabulary = doc or load_vocabulary()
    mapping = (vocabulary.get("lifecycle") or {}).get("products", {}).get(product)
    if not isinstance(mapping, dict):
        raise KeyError("unknown product: %s" % product)
    if internal not in mapping:
        raise KeyError("unknown state for %s: %s" % (product, internal))
    return mapping[internal]


def translate_verdict(source: str, internal: str,
                      doc: Dict[str, Any] | None = None) -> str:
    vocabulary = doc or load_vocabulary()
    mapping = (vocabulary.get("verdicts") or {}).get("sources", {}).get(source)
    if not isinstance(mapping, dict):
        raise KeyError("unknown verdict source: %s" % source)
    if internal not in mapping:
        raise KeyError("unknown verdict for %s: %s" % (source, internal))
    return mapping[internal]


__all__ = [
    "VOCABULARY_SCHEMA", "DEFAULT_PATH", "load_vocabulary",
    "validate_vocabulary", "translate_state", "translate_verdict",
]
