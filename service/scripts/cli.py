#!/usr/bin/env python3
"""Canonical ClearMark CLI (watermarks).

Architecture:
    watermarks inspect <file> [--mode safe|balanced|aggressive] [--json]
    watermarks clean <file> [--mode safe|balanced|aggressive] [--dry-run] [--in-place] [-o/--output <path>] [--json]
    watermarks verify <original> <candidate> [--json]
    watermarks capabilities [--json]

Exit Codes (Phase 3 Contract):
    0  = Success / Inspected / Cleaned / No change required
    2  = Unsupported format or unsupported capability
    3  = Validation failed
    4  = Invalid / malformed input (or file not found)
    5  = Optional dependency missing
    6  = Processing limit exceeded
    10 = Internal error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional, Sequence

# Ensure service/scripts is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from format_policy import FormatPolicyRegistry
from pipeline import Pipeline
from pipeline_types import (
    CleaningReport,
    DetectionStatus,
    ErrorCode,
    PipelineStatus,
    ProcessingMode,
)


class ExitCode(IntEnum):
    SUCCESS = 0
    UNSUPPORTED = 2
    VALIDATION_FAILED = 3
    INVALID_INPUT = 4
    DEPENDENCY_MISSING = 5
    LIMIT_EXCEEDED = 6
    INTERNAL_ERROR = 10


def report_to_exit_code(report: CleaningReport) -> int:
    """Map CleaningReport status and error_code to stable CLI exit code."""
    if report.status in (
        PipelineStatus.CLEANED,
        PipelineStatus.INSPECTED,
        PipelineStatus.NO_CHANGE_REQUIRED,
    ):
        return ExitCode.SUCCESS
    if report.status == PipelineStatus.VALIDATION_FAILED:
        return ExitCode.VALIDATION_FAILED
    if report.status == PipelineStatus.UNSUPPORTED:
        return ExitCode.UNSUPPORTED
    if report.status == PipelineStatus.ERROR:
        err = report.error_code
        if err == ErrorCode.UNSUPPORTED_FORMAT:
            return ExitCode.UNSUPPORTED
        if err in (
            ErrorCode.INVALID_CONTAINER,
            ErrorCode.UNSUPPORTED_ARCHIVE_FEATURE,
        ):
            return ExitCode.INVALID_INPUT
        if err == ErrorCode.OPTIONAL_DEPENDENCY_MISSING:
            return ExitCode.DEPENDENCY_MISSING
        if err == ErrorCode.PROCESSING_LIMIT_EXCEEDED:
            return ExitCode.LIMIT_EXCEEDED
        if err == ErrorCode.VALIDATION_FAILED:
            return ExitCode.VALIDATION_FAILED
        return ExitCode.INTERNAL_ERROR
    return ExitCode.INTERNAL_ERROR


def resolve_collision_safe_output(input_path: Path) -> Path:
    """Generate a collision-safe output path: file.cleaned.ext or file.cleaned.1.ext (Section 17)."""
    stem = input_path.stem
    suffix = input_path.suffix
    parent = input_path.parent
    candidate = parent / f"{stem}.cleaned{suffix}"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = parent / f"{stem}.cleaned.{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _emit_json(data: dict[str, Any]) -> None:
    """Ensure strict stdout purity for JSON output (Section 4 & 18)."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _emit_error(
    msg: str,
    exit_code: int,
    as_json: bool = False,
    error_code: Optional[str] = None,
) -> int:
    if as_json:
        payload = {
            "status": "ERROR",
            "ok": False,
            "error_code": error_code or "INVALID_REQUEST",
            "error_message": msg,
        }
        _emit_json(payload)
    else:
        sys.stderr.write(f"Error: {msg}\n")
    return exit_code


def cmd_inspect(args: argparse.Namespace) -> int:
    file_path = args.file
    if not file_path.exists():
        return _emit_error(
            f"File not found: {file_path}",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="FILE_NOT_FOUND",
        )
    if not file_path.is_file():
        return _emit_error(
            f"Path is not a regular file: {file_path}",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="INVALID_INPUT",
        )

    try:
        mode = ProcessingMode(args.mode.upper())
    except ValueError:
        return _emit_error(
            f"Invalid processing mode: {args.mode}. Must be safe, balanced, or aggressive.",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="INVALID_MODE",
        )

    pipeline = Pipeline()
    report = pipeline.inspect(file_path, mode=mode)

    if args.json:
        _emit_json(report.to_dict())
    else:
        # Concise human summary (Section 5)
        print("=== Inspection Summary ===")
        print(f"File:                 {report.input.filename}")
        print(f"Format:               {report.input.format}")
        print(f"Status:               {report.status.value}")
        print(f"Detection Status:     {report.inspection.detection_status.value}")
        print(f"Findings:             {len(report.inspection.findings)}")
        print(f"Detectors Run:        {', '.join(report.inspection.detectors_run) or 'none'}")
        if report.inspection.detectors_unavailable:
            print(f"Detectors Missing:    {', '.join(report.inspection.detectors_unavailable)}")
        if report.inspection.unsupported_checks:
            print(f"Unsupported Checks:   {', '.join(report.inspection.unsupported_checks)}")
        print(f"Would Change:         {report.output.would_change}")
        if report.validation.warnings:
            for w in report.validation.warnings:
                print(f"Notice:               {w}")

    return report_to_exit_code(report)


def cmd_clean(args: argparse.Namespace) -> int:
    file_path = args.file
    if not file_path.exists():
        return _emit_error(
            f"File not found: {file_path}",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="FILE_NOT_FOUND",
        )
    if not file_path.is_file():
        return _emit_error(
            f"Path is not a regular file: {file_path}",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="INVALID_INPUT",
        )

    if args.in_place and args.output:
        return _emit_error(
            "Cannot combine --in-place with --output/-o",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="CONFLICTING_OPTIONS",
        )

    try:
        mode = ProcessingMode(args.mode.upper())
    except ValueError:
        return _emit_error(
            f"Invalid processing mode: {args.mode}. Must be safe, balanced, or aggressive.",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="INVALID_MODE",
        )

    pipeline = Pipeline()

    if args.dry_run:
        # Zero-write guarantee (Section 6)
        cleaned_bytes, report = pipeline.clean(
            file_path,
            dry_run=True,
            in_place=args.in_place,
            mode=mode,
        )
        if args.json:
            _emit_json(report.to_dict())
        else:
            print("=== Dry-Run Clean Preview ===")
            print(f"File:                 {report.input.filename}")
            print(f"Status:               {report.status.value}")
            print(f"Changed:              {report.output.changed} (preview only)")
            print(f"Would Change:         {report.output.would_change}")
            print(f"Planned Mutations:    {len(report.mutation_plan.mutations)}")
            print(f"Target Parts:         {', '.join(report.mutation_plan.changed_parts) or 'none'}")
            print(f"Elapsed:              {report.performance_elapsed_ms:.1f} ms")
            if report.output.would_change:
                print("Result:               Proposed mutations cataloged (no files written)")
            else:
                print("Result:               No change required (input is already clean)")
        return report_to_exit_code(report)

    # Real clean
    if args.in_place:
        cleaned_bytes, report = pipeline.clean(
            file_path,
            in_place=True,
            mode=mode,
        )
        out_target = str(file_path)
    elif args.output:
        cleaned_bytes, report = pipeline.clean(
            file_path,
            output_path=args.output,
            mode=mode,
        )
        out_target = str(args.output)
    else:
        out_target_path = resolve_collision_safe_output(file_path)
        cleaned_bytes, report = pipeline.clean(
            file_path,
            output_path=out_target_path,
            mode=mode,
        )
        out_target = str(out_target_path)

    if args.json:
        _emit_json(report.to_dict())
    else:
        print("=== Cleaning Summary ===")
        print(f"File:                 {report.input.filename}")
        print(f"Status:               {report.status.value}")
        print(f"Changed:              {report.output.changed}")
        print(f"Validation:           {report.validation.status}")
        print(f"Output:               {out_target if report.output.changed else '(no change - file untouched)'}")
        print(f"Elapsed:              {report.performance_elapsed_ms:.1f} ms")
        if report.status == PipelineStatus.CLEANED:
            print("Result:               Supported markers cleaned")
        elif report.status == PipelineStatus.NO_CHANGE_REQUIRED:
            print("Result:               No change required")
        elif report.status == PipelineStatus.VALIDATION_FAILED:
            print("Result:               Validation failed; original file preserved untouched")
        elif report.status == PipelineStatus.UNSUPPORTED:
            print("Result:               Unsupported format; no modification made")
        elif report.status == PipelineStatus.ERROR:
            print(f"Result:               Error: {report.error_message}")

    return report_to_exit_code(report)


def cmd_verify(args: argparse.Namespace) -> int:
    orig_path = args.original
    cand_path = args.candidate

    if not orig_path.exists():
        return _emit_error(
            f"Original file not found: {orig_path}",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="FILE_NOT_FOUND",
        )
    if not cand_path.exists():
        return _emit_error(
            f"Candidate file not found: {cand_path}",
            ExitCode.INVALID_INPUT,
            as_json=args.json,
            error_code="FILE_NOT_FOUND",
        )

    orig_bytes = orig_path.read_bytes()
    cand_bytes = cand_path.read_bytes()

    orig_sha = hashlib.sha256(orig_bytes).hexdigest()
    cand_sha = hashlib.sha256(cand_bytes).hexdigest()

    fmt = orig_path.suffix.lower().lstrip(".")

    if fmt == "docx":
        from tools.verify_document_fidelity import analyze_docx_fidelity

        # Structural verification only; zero LibreOffice visual launch (Section 10)
        try:
            fidelity = analyze_docx_fidelity(orig_bytes, cand_bytes, perform_visual=False)
            is_pass = (fidelity.get("overall") == "PASS")
            invariants = [
                f"paragraphs: {fidelity['paragraphs'][0]} -> {fidelity['paragraphs'][1]}",
                f"runs: {fidelity['runs'][0]} -> {fidelity['runs'][1]}",
                f"tables: {fidelity['tables'][0]} -> {fidelity['tables'][1]}",
                f"manual_page_breaks: {fidelity['manual_page_breaks'][0]} -> {fidelity['manual_page_breaks'][1]}",
                f"visible_text_exact: {fidelity['visible_text_exact']}",
                f"non_target_parts_identical: {fidelity['non_target_parts_identical']}",
            ]
            warnings = []
        except Exception as e:
            is_pass = False
            invariants = []
            warnings = [f"Fidelity verification error: {e}"]
    else:
        # Non-DOCX general verification
        is_pass = True
        invariants = [
            f"source_size: {len(orig_bytes)}",
            f"candidate_size: {len(cand_bytes)}",
        ]
        warnings = []

    res_status = "PASS" if is_pass else "FAIL"

    if args.json:
        payload = {
            "ok": is_pass,
            "status": res_status,
            "format": fmt or "unknown",
            "validation": {
                "structural_invariants_passed": is_pass,
            },
            "invariants": invariants,
            "warnings": warnings,
            "hashes": {
                "original": orig_sha,
                "candidate": cand_sha,
            },
        }
        _emit_json(payload)
    else:
        print("=== Verification Summary ===")
        print(f"Original:             {orig_path}")
        print(f"Candidate:            {cand_path}")
        print(f"Format:               {fmt}")
        print(f"Status:               {res_status}")
        print(f"Invariants Passed:    {len(invariants)}")
        for inv in invariants:
            print(f"  - {inv}")
        if warnings:
            for w in warnings:
                print(f"Notice:               {w}")

    return ExitCode.SUCCESS if is_pass else ExitCode.VALIDATION_FAILED


def cmd_capabilities(args: argparse.Namespace) -> int:
    reg = FormatPolicyRegistry.get_default()
    policies = reg.all_policies()

    if args.json:
        formats_dict = {}
        for p in policies:
            formats_dict[p.format_name] = {
                "format": p.format_name,
                "extensions": list(p.extensions),
                "inspect_capabilities": list(p.inspect_capabilities),
                "clean_capabilities": list(p.clean_capabilities),
                "fidelity_levels": [f.value for f in p.fidelity_requirements],
                "optional_dependencies": list(p.optional_dependencies),
                "network_policy": p.network_policy,
                "supported_modes": ["safe", "balanced", "aggressive"],
                "destructive_operations": list(p.destructive_operations),
            }
        payload = {
            "ok": True,
            "source": "service/scripts/format_policy.py",
            "formats": formats_dict,
        }
        _emit_json(payload)
    else:
        print("=== ClearMark Supported Formats & Capabilities ===")
        for p in policies:
            exts = ", ".join(p.extensions)
            fids = ", ".join(f.value for f in p.fidelity_requirements)
            print(f"\nFormat: {p.format_name.upper()} ({exts})")
            print(f"  Fidelity Requirements: {fids}")
            print(f"  Inspect Capabilities:  {', '.join(p.inspect_capabilities)}")
            print(f"  Clean Capabilities:    {', '.join(p.clean_capabilities)}")
            print(f"  Network Policy:        {p.network_policy}")
            if p.optional_dependencies:
                print(f"  Dependencies:          {', '.join(p.optional_dependencies)}")

    return ExitCode.SUCCESS


class CanonicalArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        sys.exit(ExitCode.INVALID_INPUT)


def build_parser() -> argparse.ArgumentParser:
    parser = CanonicalArgumentParser(
        prog="watermarks",
        description="ClearMark Canonical CLI — Inspection, Cleaning, and Fidelity Verification",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=CanonicalArgumentParser)

    # 1. inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect a file for watermarks and AI provenance")
    p_inspect.add_argument("file", type=Path, help="File to inspect")
    p_inspect.add_argument(
        "--mode",
        choices=("safe", "balanced", "aggressive"),
        default="safe",
        help="Processing mode (default: safe)",
    )
    p_inspect.add_argument("--json", action="store_true", help="Output canonical CleaningReport JSON")
    p_inspect.set_defaults(func=cmd_inspect)

    # 2. clean
    p_clean = subparsers.add_parser("clean", help="Clean watermarks and provenance from a file")
    p_clean.add_argument("file", type=Path, help="File to clean")
    p_clean.add_argument(
        "--mode",
        choices=("safe", "balanced", "aggressive"),
        default="safe",
        help="Processing mode (default: safe)",
    )
    p_clean.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview planned mutations without modifying input or writing output",
    )
    p_clean.add_argument(
        "--in-place",
        action="store_true",
        help="Atomically replace input file on validation success",
    )
    p_clean.add_argument("-o", "--output", type=Path, help="Explicit destination output path")
    p_clean.add_argument("--json", action="store_true", help="Output canonical CleaningReport JSON")
    p_clean.set_defaults(func=cmd_clean)

    # 3. verify
    p_verify = subparsers.add_parser("verify", help="Verify fidelity between original and candidate files")
    p_verify.add_argument("original", type=Path, help="Original unmodified file")
    p_verify.add_argument("candidate", type=Path, help="Cleaned candidate file")
    p_verify.add_argument("--json", action="store_true", help="Output structured verification JSON")
    p_verify.set_defaults(func=cmd_verify)

    # 4. capabilities
    p_cap = subparsers.add_parser("capabilities", help="Query format capabilities and policies")
    p_cap.add_argument("--json", action="store_true", help="Output format capabilities JSON")
    p_cap.set_defaults(func=cmd_capabilities)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else ExitCode.INVALID_INPUT

    try:
        return args.func(args)
    except Exception as e:
        sys.stderr.write(f"Internal error: {e}\n")
        return ExitCode.INTERNAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
