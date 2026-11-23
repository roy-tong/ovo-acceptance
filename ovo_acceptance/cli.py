"""Command line for the OVO shared acceptance layer.

  python3 -m ovo_acceptance validate FILE [--kind task|trace|evidence|acceptance|escalation|agent_e2e]
  python3 -m ovo_acceptance bundle DIR_OR_FILE
  python3 -m ovo_acceptance publish DIR_OR_FILE --out PUBLIC_DIR --classification synthetic --by NAME

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
    result = proof_mod.validate_proof_bundle(Path(args.path))
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
        choices=["", "task", "trace", "evidence", "acceptance", "escalation", "agent_e2e"],
        help="默认按文档的 schema 字段自动识别")
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(func=_cmd_validate)

    bundle_parser = sub.add_parser(
        "bundle", help="校验一个验收包并给出 PASS/PASS_WITH_GAP/BLOCKED/FAIL")
    bundle_parser.add_argument("path", help="包含 bundle.json 的目录，或 bundle 文件")
    bundle_parser.add_argument("--json", action="store_true")
    bundle_parser.set_defaults(func=_cmd_bundle)

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
    parser = build_parser()
    args = parser.parse_args(argv)
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
