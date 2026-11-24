"""Command line for the OVO shared acceptance layer.

  python3 -m ovo_acceptance validate FILE [--kind task|trace|evidence|acceptance|escalation|agent_e2e|result_receipt|delegated_task|service_capability]
  python3 -m ovo_acceptance bundle DIR_OR_FILE
  python3 -m ovo_acceptance publish DIR_OR_FILE --out PUBLIC_DIR --classification synthetic --by NAME
  python3 -m ovo_acceptance vocabulary [--json]
  python3 -m ovo_acceptance adapter --proof DIR --out FILE [--by NAME]
  python3 -m ovo_acceptance adapter --product askovo|growovo|verovo --out FILE
  python3 -m ovo_acceptance case list|show|incidents|index|validate|replay|verify

Exit codes: 0 accepted, 1 validation failed, 2 usage or unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from . import model, proof as proof_mod, publish as publish_mod

BUNDLE_FILENAMES = ("bundle.json", "acceptance-bundle.json")


def _load_bundle(path_text: str) -> Dict[str, Any]:
    path = Path(path_text)
    if path.is_dir():
        for name in BUNDLE_FILENAMES:
            candidate = path / name
            if candidate.is_file():
                return model.load_json(candidate)
        raise model.AcceptanceError(
            "%s has no %s" % (path, " or ".join(BUNDLE_FILENAMES)))
    return model.load_json(path)


def _print_errors(errors: List[Dict[str, str]]) -> None:
    for item in errors:
        print("  [%s] %s: %s" % (item.get("code"), item.get("path"),
                                 item.get("message")))


def _cmd_validate(args: argparse.Namespace) -> int:
    doc = model.load_json(Path(args.file))
    kind = args.kind or model.detect_kind(doc) or ""
    errors = model.validate_document(doc, kind)
    payload = {
        "file": str(args.file),
        "kind": kind or "unknown",
        "ok": not errors,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if errors:
            print("校验失败：%s（%s）" % (args.file, kind or "unknown"))
            _print_errors(errors)
        else:
            print("校验通过：%s（%s）" % (args.file, kind or "unknown"))
    return 0 if not errors else 1


def _cmd_bundle(args: argparse.Namespace) -> int:
    bundle = _load_bundle(args.path)
    result = model.validate_bundle(bundle)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("验收结论：%s（contract %s）"
              % (result["verdict"], result["contract_id"] or "?"))
        for item in result["deliverables"]:
            print("  - %s: %s（%d 条记录：%s）"
                  % (item["deliverable_id"], item["status"], item["records"],
                     ", ".join(item["verdicts"]) or "—"))
        if result["errors"]:
            print("问题：")
            _print_errors(result["errors"])
        elif result["verdict"] == "PASS_WITH_GAP":
            print("注意：存在已署名接受的差距，结论不能当作完整通过。")
        elif result["verdict"] == "BLOCKED":
            print("注意：存在未证明项或待重做项，尚未通过验收。")
    return 0 if result["ok"] else 1


def _cmd_proof(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.is_dir():
        errors = [{"code": "USAGE", "path": str(root),
                   "message": "proof 只接受目录；传 bundle 文件本身或不存在路径无法校验"}]
        if args.json:
            print(json.dumps({"status": "INVALID", "errors": errors},
                             ensure_ascii=False, indent=2))
        else:
            print("证明校验：INVALID（用法错误）")
            _print_errors(errors)
        return 2
    if not (root / "bundle.json").is_file():
        errors = [{"code": "USAGE", "path": str(root / "bundle.json"),
                   "message": "目录必须包含 bundle.json（proof 只认 bundle.json，不认 acceptance-bundle.json）"}]
        if args.json:
            print(json.dumps({"status": "INVALID", "errors": errors},
                             ensure_ascii=False, indent=2))
        else:
            print("证明校验：INVALID（用法错误）")
            _print_errors(errors)
        return 2
    result = proof_mod.validate_proof_bundle(root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("证明校验：%s（proof %s）" % (result["status"], result["proof_id"] or "?"))
        for check in result["checks"]:
            print("  - %s: %s / %s" % (
                check.get("check_id"), check.get("level"), check.get("status")))
            if check.get("reason"):
                print("    %s" % check["reason"])
        if result["errors"]:
            _print_errors(result["errors"])
    return 0 if result["ok"] else 1


def _cmd_vocabulary(args: argparse.Namespace) -> int:
    from . import vocabulary
    doc = vocabulary.load_vocabulary()
    errors = vocabulary.validate_vocabulary(doc)
    lifecycle = doc.get("lifecycle") or {}
    payload = {
        "ok": not errors,
        "errors": errors,
        "products": sorted((doc.get("product_identifiers") or {}).keys()),
        "lifecycle_states": len(lifecycle.get("canonical") or []),
        "verdict_sources": sorted((doc.get("verdicts") or {}).get("sources", {}).keys()),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("词汇映射：%s" % ("通过" if not errors else "失败"))
        print("  产品：%s" % ", ".join(payload["products"]))
        print("  生命周期状态：%d" % payload["lifecycle_states"])
        print("  判决来源：%s" % ", ".join(payload["verdict_sources"]))
        for item in errors:
            print("  - %s" % item)
    return 0 if not errors else 1


def _cmd_adapter(args: argparse.Namespace) -> int:
    from . import adapters
    if bool(args.proof) == bool(args.product):
        print("ERROR: pass exactly one of --proof or --product", file=sys.stderr)
        return 2
    try:
        if args.proof:
            document = adapters.receipt_from_proof_bundle(
                args.proof, reviewed_by=args.by)
            kind = "result_receipt"
        else:
            document = adapters.capability_descriptor(args.product)
            kind = "service_capability"
    except (ValueError, OSError, model.AcceptanceError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    if args.json:
        print(json.dumps(document, ensure_ascii=False, indent=2))
    else:
        print("已写入 %s（%s）" % (out, kind))
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    bundle = _load_bundle(args.path)
    result = publish_mod.publish_bundle(
        bundle, Path(args.out), classification=args.classification,
        approved_by=args.by)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("公开验收包：%s（%s）" % (result["out"], result["verdict"]))
        print("原始输入未复制；打开 index.html 查看，或重放 bundle.json。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ovo-acceptance",
        description="OVO 共同验收层：任务合同、执行轨迹、证据账本与验收结论")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser(
        "validate", help="校验一份合同/轨迹/证据/验收/升级记录")
    validate_parser.add_argument("file")
    validate_parser.add_argument(
        "--kind", default="",
        choices=["", "task", "trace", "evidence", "acceptance", "escalation", "agent_e2e",
                 "result_receipt", "delegated_task", "service_capability"],
        help="默认按文档的 schema 字段自动识别")
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(func=_cmd_validate)

    bundle_parser = sub.add_parser(
        "bundle", help="校验一个验收包并给出 PASS/PASS_WITH_GAP/BLOCKED/FAIL/INVALID")
    bundle_parser.add_argument("path", help="包含 bundle.json 的目录，或 bundle 文件")
    bundle_parser.add_argument("--json", action="store_true")
    bundle_parser.set_defaults(func=_cmd_bundle)

    vocabulary_parser = sub.add_parser(
        "vocabulary", help="校验家族词汇映射表并列出产品、生命周期状态与判决来源")
    vocabulary_parser.add_argument("--json", action="store_true")
    vocabulary_parser.set_defaults(func=_cmd_vocabulary)

    adapter_parser = sub.add_parser(
        "adapter", help="从 Proof Bundle 生成 C-01 结果凭证，或输出产品能力描述")
    adapter_parser.add_argument("--proof", default="", help="Proof Bundle 目录")
    adapter_parser.add_argument("--product", default="",
                                choices=["", "askovo", "growovo", "verovo"])
    adapter_parser.add_argument("--out", required=True, help="输出 JSON 文件")
    adapter_parser.add_argument("--by", default="", help="具名审阅人（可选）")
    adapter_parser.add_argument("--json", action="store_true")
    adapter_parser.set_defaults(func=_cmd_adapter)

    proof_parser = sub.add_parser(
        "proof", help="校验可携带 Proof Bundle 的投影、五态、证明等级与重放清单")
    proof_parser.add_argument("path", help="包含 bundle/contract/trace/checks/proof/replay 的目录")
    proof_parser.add_argument("--json", action="store_true")
    proof_parser.set_defaults(func=_cmd_proof)

    publish_parser = sub.add_parser(
        "publish", help="发布不含原始输入的公开验收投影与任务模板")
    publish_parser.add_argument("path", help="验收包目录或 bundle 文件")
    publish_parser.add_argument("--out", required=True, help="为空的输出目录")
    publish_parser.add_argument(
        "--classification", required=True,
        choices=list(publish_mod.PUBLIC_CLASSIFICATIONS),
        help="synthetic 或已获授权的 public-redacted；私有包默认拒绝")
    publish_parser.add_argument("--by", required=True, help="具名发布人")
    publish_parser.add_argument("--json", action="store_true")
    publish_parser.set_defaults(func=_cmd_publish)
    return parser


def main(argv: List[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "case":
        from . import casebook
        return int(casebook.main(arguments[1:]))
    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        return int(args.func(args))
    except model.AcceptanceError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
