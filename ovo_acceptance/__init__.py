"""OVO shared acceptance layer: task contract → trace → evidence → verdict."""

from .model import (  # noqa: F401
    ACCEPTANCE_SCHEMA,
    BUNDLE_SCHEMA,
    CONTEXT_FIELDS,
    DECISIONS,
    ESCALATION_SCHEMA,
    GENERALIZATIONS,
    KIND_BY_SCHEMA,
    LEDGER_SCHEMA,
    SCHEMA_BY_KIND,
    TASK_SCHEMA,
    TRACE_SCHEMA,
    TRIGGERS,
    VERDICTS,
    AcceptanceError,
    detect_kind,
    load_json,
    load_schema,
    validate_acceptance_record,
    validate_bundle,
    validate_document,
    validate_escalation_record,
    validate_evidence_ledger,
    validate_execution_trace,
    validate_task_contract,
)

__version__ = "0.3.0"
