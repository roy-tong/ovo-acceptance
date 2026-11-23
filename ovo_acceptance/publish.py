"""Publish a source-free, replayable public view of an acceptance bundle."""
from __future__ import annotations

import copy
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from . import model

PUBLIC_SCHEMA = "ovo.public-proof/1"
TEMPLATE_SCHEMA = "ovo.task-template/1"
PUBLIC_CLASSIFICATIONS = ("synthetic", "public-redacted")


class PublicationError(model.AcceptanceError):
    pass


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _public_projection(bundle: Dict[str, Any]) -> Dict[str, Any]:
    public_strings = frozenset({
        "schema", "product", "kind", "status", "trust", "generalization",
        "verdict", "decision", "trigger", "version", "source_hash",
        "contract_id", "trace_id", "ledger_id", "evidence_id", "acceptance_id",
        "escalation_id", "deliverable_id", "step_id", "id", "retry_of",
        "cache_hit_of", "evidence_refs", "created_at", "started_at", "finished_at",
        "ended_at", "observed_at", "checked_at", "raised_at", "decided_at", "deadline",
    })
    redactions: Dict[str, str] = {}

    def redacted(value: str) -> str:
        if value not in redactions:
            redactions[value] = "redacted:%d" % (len(redactions) + 1)
        return redactions[value]

    def walk(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            return {key: walk(item, key) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, field) for item in value]
        if isinstance(value, str) and field not in public_strings:
            return redacted(value)
        return value

    return walk(bundle)


def _template(bundle: Dict[str, Any]) -> Dict[str, Any]:
    task = bundle.get("task_contract") or {}
    return {
        "schema": TEMPLATE_SCHEMA,
        "based_on_contract": task.get("contract_id"),
        "product": task.get("product"),
        "goal": task.get("goal"),
        "deliverables": copy.deepcopy(task.get("deliverables") or []),
        "note": "Template reuse starts a new review; it does not reuse this verdict.",
    }


def _render_html(bundle: Dict[str, Any], validation: Dict[str, Any],
                 classification: str, approved_by: str) -> str:
    task = bundle.get("task_contract") or {}
    rows: List[str] = []
    for item in validation.get("deliverables") or []:
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(str(item.get("deliverable_id") or "")),
            html.escape(str(item.get("status") or "")),
            html.escape(", ".join(item.get("verdicts") or []))))
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · OVO public proof</title>
<style>body{max-width:900px;margin:40px auto;padding:0 20px;font:16px/1.6 system-ui,sans-serif;color:#18221f}table{border-collapse:collapse;width:100%%}th,td{text-align:left;padding:10px;border-bottom:1px solid #ccd5d1}code,pre{font-family:ui-monospace,monospace}pre{padding:16px;background:#101816;color:#eef7f3;overflow:auto}.badge{display:inline-block;padding:3px 10px;border:1px solid #6d8078;border-radius:16px}.note{padding:14px;border-left:4px solid #8b6b23;background:#faf6e9}</style></head>
<body><main><p class="badge">%s · %s</p><h1>%s</h1>
<p>公开验收投影，不包含原始输入文件。发布人：%s。</p>
<p class="note">此页证明合同、证据引用与验收记录可以一起复核，不证明市场需求、普遍能力或业务结果。</p>
<table><thead><tr><th>交付物</th><th>状态</th><th>验收判定</th></tr></thead><tbody>%s</tbody></table>
<h2>查看与复用</h2><ul><li><a href="bundle.json">公开验收包</a></li><li><a href="template.json">任务模板</a></li><li><a href="share.json">发布清单与哈希</a></li></ul>
<h2>本地重放</h2><pre>python3 -m ovo_acceptance bundle bundle.json --json</pre>
</main></body></html>""" % (
        html.escape(str(task.get("product") or "OVO")),
        html.escape(str(validation.get("verdict") or "UNPROVEN")),
        html.escape(classification), html.escape(str(task.get("goal") or "")),
        html.escape(approved_by), "".join(rows))


def publish_bundle(bundle: Dict[str, Any], out_dir: Path, *, classification: str,
                   approved_by: str) -> Dict[str, Any]:
    approver = str(approved_by or "").strip()
    if not approver:
        raise PublicationError("公开证据包需要具名发布人")
    if classification not in PUBLIC_CLASSIFICATIONS:
        raise PublicationError("默认私有：只有 synthetic 或已授权 public-redacted 包可公开")
    validation = model.validate_bundle(bundle)
    if validation.get("errors"):
        raise PublicationError("验收包存在契约错误，不能公开")
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise PublicationError("公开输出目录必须为空")
    out.mkdir(parents=True, exist_ok=True)
    projected = _public_projection(bundle)
    projected_validation = model.validate_bundle(projected)
    if projected_validation.get("errors"):
        raise PublicationError("公开投影未能保持验收契约")
    template = _template(projected)
    _write_json(out / "bundle.json", projected)
    _write_json(out / "template.json", template)
    (out / "index.html").write_text(
        _render_html(projected, projected_validation, classification, approver),
        encoding="utf-8")
    share = {
        "schema": PUBLIC_SCHEMA,
        "classification": classification,
        "approved_by": approver,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "verdict": projected_validation["verdict"],
        "files": [
            {"path": name, "sha256": _sha(out / name)}
            for name in ("bundle.json", "template.json", "index.html")
        ],
        "boundary": "Source bytes are excluded. Public replay checks the acceptance contracts only.",
    }
    _write_json(out / "share.json", share)
    return {"verdict": projected_validation["verdict"], "bundle": projected,
            "template": template, "share": share, "out": str(out)}


__all__ = ["PUBLIC_SCHEMA", "TEMPLATE_SCHEMA", "PublicationError", "publish_bundle"]
