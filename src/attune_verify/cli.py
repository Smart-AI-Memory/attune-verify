"""Command-line publication gate. Exit 0 pass, 1 rejected, 2 invalid invocation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from attune_verify import VerifyContext, verify
from attune_verify.evaluation import evaluate
from attune_verify.evidence import capture, impact
from attune_verify.files import contained, read_text, write_json
from attune_verify.manifest import load_context


def main(argv: list[str] | None = None) -> int:
    """Check documents with declared context and print structured evidence."""
    parser = argparse.ArgumentParser(prog="attune-verify")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Verify Markdown against declared project sources")
    check.add_argument("files", nargs="+", type=Path)
    check.add_argument("--context", type=Path)
    check.add_argument("--format", choices=("text", "json"), default="text")
    check.add_argument(
        "--policy",
        choices=("strict", "errors"),
        default="strict",
        help="strict rejects unknown or empty verification; errors uses legacy ok",
    )
    check.add_argument("--output", type=Path, help="Write JSON under the current directory")
    receipts = sub.add_parser("receipts", help="Capture conservative Python API evidence")
    receipts.add_argument("files", nargs="+", type=Path)
    impact_parser = sub.add_parser("impact", help="Recheck saved Python API evidence")
    impact_parser.add_argument("input", type=Path)
    evaluation = sub.add_parser("evaluate", help="Measure explicitly labeled document cases")
    evaluation.add_argument("input", type=Path)
    for command in (receipts, impact_parser, evaluation):
        command.add_argument("--context", type=Path)
        command.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        ctx = load_context(args.context) if args.context else VerifyContext(project_root=Path.cwd())
        inputs = list(getattr(args, "files", []))
        if hasattr(args, "input"):
            inputs.append(args.input)
        if args.context:
            inputs.append(args.context)
        if args.output and args.output.resolve() in {p.resolve() for p in inputs}:
            raise ValueError("Output must not overwrite an input document or context")
        if args.command != "check":
            if args.command == "receipts":
                report = capture(args.files, ctx)
            else:
                payload = json.loads(read_text(args.input))
                report = (
                    impact(payload, ctx) if args.command == "impact" else evaluate(payload, ctx)
                )
            if args.output:
                write_json(args.output, report, root=Path.cwd())
            print(json.dumps(report, indent=2))
            return 1 if report.get("needs_recheck") else 0
        documents = []
        for filename in args.files:
            path = contained(filename.resolve(), ctx.project_root)
            result = verify(read_text(path), replace(ctx, document_path=path))
            documents.append(
                {
                    "file": str(path.relative_to(ctx.project_root)),
                    "passed": result.passes() if args.policy == "strict" else result.ok,
                    **result.to_dict(),
                }
            )
        report = {
            "schema_version": 1,
            "policy": args.policy,
            "documents": documents,
            "passed": all(doc["passed"] for doc in documents),
        }
        if args.output:
            write_json(args.output, report, root=Path.cwd())
        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            for doc in documents:
                coverage = doc["coverage"]
                print(
                    f"{doc['file']}: {'PASS' if doc['passed'] else 'FAIL'} ({doc['status']}) — "
                    f"{coverage['verified']} verified, {coverage['refuted']} refuted, "
                    f"{coverage['unknown']} unknown; {coverage['total']} supported claims"
                )
                for finding in doc["findings"]:
                    print(
                        f"  {finding['severity']} {finding['location'] or ''}: {finding['detail']}"
                    )
                for claim in doc["claims"]:
                    if claim["status"] == "unknown":
                        print(
                            f"  unknown {claim['location'] or ''}: {claim['subject']} — "
                            f"{claim['detail']}"
                        )
                if not coverage["total"]:
                    print("  No supported claims extracted; ordinary prose was not fact-checked.")
        return 0 if report["passed"] else 1
    except (OSError, ValueError, TypeError) as exc:
        print(f"attune-verify: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
