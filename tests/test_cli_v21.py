"""Tests for Phase 3: Canonical CLI (watermarks) and Normalization Contract.

Covers:
- CLI inspect JSON & Human output
- CLI clean JSON & Human output
- CLI dry-run JSON
- CLI invalid mode (exit code 4)
- CLI unsupported format (exit code 2)
- CLI --in-place success
- CLI --in-place atomic validation failure safety
- CLI collision-safe output naming
- CLI verify command (structural invariants)
- CLI capabilities command
- CLI stdout purity (valid JSON on stdout, no debug/banners)
- Zero network socket activity
- Report privacy invariant
"""

from __future__ import annotations

import io
import json
import os
import socket
import sys
from pathlib import Path
import pytest

from service.scripts.cli import ExitCode, build_parser, main, resolve_collision_safe_output
from service.scripts.pipeline_types import (
    CleaningReport,
    DetectionStatus,
    PipelineStatus,
    ProcessingMode,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CANDIDATE_DOCX = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"


def _run_cli(args: list[str], capsys) -> tuple[int, str, str]:
    """Invoke CLI main() in-process and capture stdout/stderr."""
    exit_code = main(args)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# 1. CLI inspect JSON
def test_cli_inspect_json(tmp_path: Path, capsys):
    test_file = tmp_path / "test.docx"
    test_file.write_bytes(GOLDEN_DOCX.read_bytes())

    code, out, err = _run_cli(["inspect", str(test_file), "--json"], capsys)
    assert code == ExitCode.SUCCESS

    # Stdout must be strictly valid JSON
    data = json.loads(out)
    assert isinstance(data, dict)
    assert data["status"] in ("INSPECTED", "CLEANED", "NO_CHANGE_REQUIRED")
    assert data["input"]["filename"] == "test.docx"
    assert data["input"]["format"] == "docx"

    # Must deserialize cleanly to canonical CleaningReport
    report = CleaningReport.from_dict(data)
    assert report.status == PipelineStatus.INSPECTED
    assert report.input.format == "docx"
    assert len(report.inspection.findings) > 0


# 2. CLI clean JSON & dry-run JSON
def test_cli_clean_json_output(tmp_path: Path, capsys):
    test_file = tmp_path / "test.docx"
    test_file.write_bytes(GOLDEN_DOCX.read_bytes())
    out_file = tmp_path / "out.docx"

    code, out, err = _run_cli(["clean", str(test_file), "-o", str(out_file), "--json"], capsys)
    assert code == ExitCode.SUCCESS
    assert out_file.exists()

    data = json.loads(out)
    report = CleaningReport.from_dict(data)
    assert report.status in (PipelineStatus.CLEANED, PipelineStatus.NO_CHANGE_REQUIRED)
    assert report.output.changed is True
    assert report.output.output_path == str(out_file)


def test_cli_clean_dry_run_json(tmp_path: Path, capsys):
    test_file = tmp_path / "test.docx"
    orig_bytes = GOLDEN_DOCX.read_bytes()
    test_file.write_bytes(orig_bytes)

    code, out, err = _run_cli(["clean", str(test_file), "--dry-run", "--json"], capsys)
    assert code == ExitCode.SUCCESS

    # Input file must be byte-identical
    assert test_file.read_bytes() == orig_bytes

    data = json.loads(out)
    report = CleaningReport.from_dict(data)
    assert report.output.changed is False
    assert report.output.would_change is True
    assert len(report.mutation_plan.mutations) > 0


# 3. CLI human output formatting (inspect & clean)
def test_cli_inspect_human_output(tmp_path: Path, capsys):
    test_file = tmp_path / "test.docx"
    test_file.write_bytes(GOLDEN_DOCX.read_bytes())

    code, out, err = _run_cli(["inspect", str(test_file)], capsys)
    assert code == ExitCode.SUCCESS

    # Human summary requirements (Section 5)
    assert "=== Inspection Summary ===" in out
    assert "Format:" in out
    assert "Status:" in out
    assert "Detection Status:" in out
    assert "Findings:" in out
    assert "Would Change:" in out

    # Privacy / accuracy checks
    assert "watermark completely removed" not in out
    assert "Lorem ipsum" not in out  # No document body text


def test_cli_clean_human_output(tmp_path: Path, capsys):
    test_file = tmp_path / "test.docx"
    test_file.write_bytes(GOLDEN_DOCX.read_bytes())
    out_file = tmp_path / "cleaned.docx"

    code, out, err = _run_cli(["clean", str(test_file), "-o", str(out_file)], capsys)
    assert code == ExitCode.SUCCESS

    # Human summary requirements (Section 5)
    assert "=== Cleaning Summary ===" in out
    assert "Status:" in out
    assert "Changed:" in out
    assert "Validation:" in out
    assert "Output:" in out
    assert "Elapsed:" in out
    assert "Supported markers cleaned" in out
    assert "watermark completely removed" not in out


# 4. CLI exit codes contract
def test_cli_invalid_mode_exit_code(tmp_path: Path, capsys):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello World", encoding="utf-8")

    # Invalid choice caught by parser
    code, out, err = _run_cli(["clean", str(test_file), "--mode", "super_aggressive"], capsys)
    assert code == ExitCode.INVALID_INPUT
    assert "error" in err.lower()
    # Ensure no Python traceback is leaked to stderr
    assert "Traceback (most recent call last)" not in err


def test_cli_unsupported_format_exit_code(tmp_path: Path, capsys):
    bad_file = tmp_path / "archive.xyz"
    bad_file.write_bytes(b"\x00\x01\x02\x03\x04")

    code, out, err = _run_cli(["inspect", str(bad_file)], capsys)
    assert code == ExitCode.UNSUPPORTED


def test_cli_file_not_found_exit_code(tmp_path: Path, capsys):
    missing_file = tmp_path / "non_existent.docx"
    code, out, err = _run_cli(["inspect", str(missing_file)], capsys)
    assert code == ExitCode.INVALID_INPUT
    assert "not found" in err.lower()


# 5. CLI --in-place success & atomic failure safety
def test_cli_in_place_success(tmp_path: Path, capsys):
    test_file = tmp_path / "doc.docx"
    orig_bytes = GOLDEN_DOCX.read_bytes()
    test_file.write_bytes(orig_bytes)

    code, out, err = _run_cli(["clean", str(test_file), "--in-place"], capsys)
    assert code == ExitCode.SUCCESS
    assert test_file.exists()
    cleaned_bytes = test_file.read_bytes()
    assert cleaned_bytes != orig_bytes  # Successfully updated in-place


def test_cli_in_place_atomic_validation_failure_safety(tmp_path: Path, monkeypatch, capsys):
    """Section 16: When validation fails, sibling temp file is deleted and original file remains untouched."""
    test_file = tmp_path / "doc_fail.docx"
    orig_bytes = GOLDEN_DOCX.read_bytes()
    test_file.write_bytes(orig_bytes)

    # Force a validation failure inside docx lossless cleaning
    def _failing_clean(*args, **kwargs):
        return orig_bytes, {
            "error": "forced validation failure: visible text mismatch",
            "validation": None,
        }

    import docx.cleaner
    monkeypatch.setattr(docx.cleaner, "clean_docx_lossless", _failing_clean)

    code, out, err = _run_cli(["clean", str(test_file), "--in-place"], capsys)
    assert code == ExitCode.VALIDATION_FAILED

    # Invariant: Original file must remain byte-identical
    assert test_file.read_bytes() == orig_bytes

    # Invariant: No temporary files left behind in directory
    entries = list(tmp_path.iterdir())
    assert entries == [test_file]


# 6. Output collision-safe naming
def test_resolve_collision_safe_output(tmp_path: Path):
    src = tmp_path / "report.docx"
    src.write_bytes(b"data")

    first = resolve_collision_safe_output(src)
    assert first == tmp_path / "report.cleaned.docx"

    # Create first collision
    first.write_bytes(b"cleaned1")
    second = resolve_collision_safe_output(src)
    assert second == tmp_path / "report.cleaned.1.docx"

    # Create second collision
    second.write_bytes(b"cleaned2")
    third = resolve_collision_safe_output(src)
    assert third == tmp_path / "report.cleaned.2.docx"


# 7. CLI verify command
def test_cli_verify_golden_vs_candidate(capsys):
    code, out, err = _run_cli(["verify", str(GOLDEN_DOCX), str(CANDIDATE_DOCX), "--json"], capsys)
    assert code == ExitCode.SUCCESS

    data = json.loads(out)
    assert data["ok"] is True
    assert data["status"] == "PASS"
    assert data["format"] == "docx"
    assert data["validation"]["structural_invariants_passed"] is True
    assert len(data["invariants"]) >= 5


def test_cli_verify_failure_exit_code(tmp_path: Path, capsys):
    corrupt_candidate = tmp_path / "corrupt.docx"
    # Overwrite candidate with partial/corrupted content
    corrupt_candidate.write_bytes(b"PK\x03\x04corrupted zip payload")

    code, out, err = _run_cli(["verify", str(GOLDEN_DOCX), str(corrupt_candidate)], capsys)
    assert code == ExitCode.VALIDATION_FAILED
    assert "FAIL" in out


def test_cli_verify_unsupported_format(tmp_path: Path, capsys):
    orig = tmp_path / "orig.txt"
    orig.write_text("orig text", encoding="utf-8")
    cand = tmp_path / "cand.txt"
    cand.write_text("cand text", encoding="utf-8")

    code, out, err = _run_cli(["verify", str(orig), str(cand), "--json"], capsys)
    assert code == ExitCode.UNSUPPORTED
    data = json.loads(out)
    assert data["ok"] is False
    assert data["status"] == "UNSUPPORTED"
    assert data["error_code"] == "UNSUPPORTED_VERIFICATION_CAPABILITY"
    assert "Verification capability is currently supported only for docx" in data["error_message"]


# 8. CLI capabilities command
def test_cli_capabilities_command(capsys):
    code, out, err = _run_cli(["capabilities", "--json"], capsys)
    assert code == ExitCode.SUCCESS

    data = json.loads(out)
    assert data["ok"] is True
    assert data["source"] == "service/scripts/format_policy.py"
    assert "docx" in data["formats"]
    assert "txt" in data["formats"]
    assert "png" in data["formats"]


# 9. CLI zero network isolation
def test_cli_zero_network_isolation(tmp_path: Path, monkeypatch, capsys):
    """Section 19: Prove CLI inspect and dry-run make 0 network calls."""
    def _forbidden_network(*args, **kwargs):
        raise AssertionError("CRITICAL: Network attempt during local CLI execution!")

    monkeypatch.setattr(socket, "socket", _forbidden_network)
    monkeypatch.setattr(socket, "create_connection", _forbidden_network)

    test_file = tmp_path / "local.docx"
    test_file.write_bytes(GOLDEN_DOCX.read_bytes())

    code_insp, out_insp, _ = _run_cli(["inspect", str(test_file), "--json"], capsys)
    assert code_insp == ExitCode.SUCCESS

    code_dry, out_dry, _ = _run_cli(["clean", str(test_file), "--dry-run", "--json"], capsys)
    assert code_dry == ExitCode.SUCCESS


# 10. CLI report privacy invariant
def test_cli_report_privacy(tmp_path: Path, capsys):
    test_file = tmp_path / "sensitive.txt"
    test_file.write_text("CONFIDENTIAL_PASSWORD_12345\u200Bmarker", encoding="utf-8")

    code, out, _ = _run_cli(["inspect", str(test_file), "--json"], capsys)
    assert code == ExitCode.SUCCESS

    assert "CONFIDENTIAL_PASSWORD_12345" not in out
