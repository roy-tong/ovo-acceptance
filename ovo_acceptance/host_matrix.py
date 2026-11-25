"""Host Compatibility Matrix projection with explicit measured and unmeasured states."""
from __future__ import annotations

import copy

SCHEMA = "ovo.host-compatibility/1"
RESULT_SCHEMA = "ovo.host-compatibility-result/1"
PRODUCTS = ("askovo", "growovo", "verovo")
CAPABILITIES = ("skill_discovery", "cli_install_execute", "mcp_call", "high_level_task",
                "file_data_access", "multi_session_recovery", "background_execution",
                "natural_language_delivery")
STATUSES = ("PASS", "FAIL", "NOT_RUN", "UNSUPPORTED", "CAPABILITY_ONLY")


def _validate(document):
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("host compatibility schema must be %s" % SCHEMA)
    if not str(document.get("matrix_id") or "").strip():
        raise ValueError("matrix_id is required")
    rows = document.get("observations")
    if not isinstance(rows, list) or not rows:
        raise ValueError("observations must be a non-empty array")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each host observation must be an object")
        for key in ("host", "model", "capability", "status"):
            if not str(row.get(key) or "").strip():
                raise ValueError("host observation.%s is required" % key)
        if row.get("product") not in PRODUCTS:
            raise ValueError("host observation product must be askovo, growovo or verovo")
        if row["capability"] not in CAPABILITIES:
            raise ValueError("host capability is not registered")
        if row["status"] not in STATUSES:
            raise ValueError("host capability status is not registered")
        key = (row["host"], row["model"], row["product"], row["capability"])
        if key in seen:
            raise ValueError("duplicate host capability observation: %s" % (key,))
        seen.add(key)
        if row["status"] in ("PASS", "FAIL"):
            if not str(row.get("run_ref") or "").strip():
                raise ValueError("run_ref is required for measured host capability status")
            if not str(row.get("evidence_ref") or "").strip():
                raise ValueError("evidence_ref is required for measured host capability status")
        if row["status"] == "CAPABILITY_ONLY" and not str(row.get("evidence_ref") or "").strip():
            raise ValueError("CAPABILITY_ONLY requires evidence_ref")
        if row["status"] == "UNSUPPORTED" and not str(row.get("note") or "").strip():
            raise ValueError("UNSUPPORTED requires a note")


def summarize(document):
    _validate(document)
    hosts = {}
    counts = {status: 0 for status in STATUSES}
    for source in document["observations"]:
        row = copy.deepcopy(source)
        counts[row["status"]] += 1
        host_key = (row["host"], row["model"], row["product"])
        host = hosts.setdefault(host_key, {
            "host": row["host"], "model": row["model"], "product": row["product"],
            "capabilities": {},
        })
        host["capabilities"][row["capability"]] = row
    rendered = []
    for key in sorted(hosts):
        host = hosts[key]
        capabilities = host["capabilities"]
        high = capabilities.get("high_level_task", {}).get("status", "NOT_RUN")
        natural = capabilities.get("natural_language_delivery", {}).get("status", "NOT_RUN")
        if high == "PASS" and natural == "PASS":
            core = "PASS"
        elif "FAIL" in (high, natural):
            core = "FAIL"
        else:
            core = "INCOMPLETE"
        background = capabilities.get("background_execution", {}).get("status", "NOT_RUN")
        continuous = background if background in ("PASS", "FAIL", "CAPABILITY_ONLY", "UNSUPPORTED") \
            else "NOT_ESTABLISHED"
        values = list(capabilities.values())
        rendered.append(dict(
            host, core_l3_status=core, continuous_runtime_status=continuous,
            coverage={
                "declared_capabilities": len(values),
                "measured": sum(row["status"] in ("PASS", "FAIL") for row in values),
                "capability_only": sum(row["status"] == "CAPABILITY_ONLY" for row in values),
                "measured_or_capability_observations": sum(
                    row["status"] in ("PASS", "FAIL", "CAPABILITY_ONLY") for row in values),
                "not_run": sum(row["status"] == "NOT_RUN" for row in values),
                "unsupported": sum(row["status"] == "UNSUPPORTED" for row in values),
                "undisclosed_registered_capabilities": len(CAPABILITIES) - len(values),
            }))
    return {
        "schema": RESULT_SCHEMA,
        "matrix_id": document["matrix_id"],
        "hosts": rendered,
        "summary": counts,
        "registered_capabilities": list(CAPABILITIES),
        "core_l3_rule": "high_level_task and natural_language_delivery must both be PASS; source evidence qualification remains separate",
        "continuous_runtime_rule": "CAPABILITY_ONLY never becomes PASS; background_execution needs its own measured evidence",
        "boundary": "A matrix projection, not a new test run. NOT_RUN and UNSUPPORTED stay distinct. Linked agent-e2e evidence must independently satisfy fresh-session, real-input and human-acceptance rules before claiming real L3 or L4 success.",
    }
