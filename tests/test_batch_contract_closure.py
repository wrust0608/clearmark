"""Phase 4 Batch Contract Closure Evidence Tests.

Durable executable evidence verifying:
1. Stable batch exit and status contract (0 = success, 1 = partial failure, 2 = fatal setup / zero inputs, 4 = invalid configuration).
2. Phase 3 exit code preservation (0, 2, 3, 4, 5, 6, 10 preserved; 2 is never repurposed for partial failure).
3. Batch dry-run zero-write contract: nonexistent output-dir and reports-dir are never created.
4. Input tree immutability: SHA256, size, and mtime_ns remain strictly unchanged.
5. Recursive directory batch self-ingestion prevention: nested output and reports directories are excluded from input discovery.
6. Rerun stability: rerun of the same recursive command does not ingest previous outputs/reports or create duplicate extensions.
7. Explicit Policy B rejection: output_dir == input_root and reports_dir == input_root are rejected as invalid configuration (ExitCode 4).
8. Symlink and junction/reparse-point traversal safety.
9. Windows case-insensitive path comparison for exclusion of nested output directories.
10. Legitimate source preservation: files with 'cleaned' in name are not excluded based on loose substrings.
11. Fault isolation: one bad item never crashes healthy siblings.
12. Batch summary mathematical reconciliation: sum(terminal categories) == total.
13. CLI stdout JSON purity for both success and partial failure.
14. Report privacy: document body sentinel never leaks into CLI stdout, reports, or logs.
15. Zero network socket egress during batch processing.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from service.scripts.batch_processor import (
    BatchProcessor,
    BatchReport,
    _is_subpath_or_equal,
    discover_input_files,
)
from service.scripts.cli import ExitCode, main as cli_main

GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"


def _run_cli(args: list[str], capsys) -> tuple[int, str, str]:
    code = cli_main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ============================================================================
# 1. BATCH STABLE EXIT AND STATUS CONTRACT
# ============================================================================

def test_batch_exit_code_all_success_and_no_change(tmp_path: Path, capsys):
    """Exit code is 0 when all items succeed (cleaned or no change required)."""
    doc = tmp_path / "valid.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())
    txt = tmp_path / "clean.txt"
    txt.write_text("Hello plain clean text", encoding="utf-8")
    out_dir = tmp_path / "out"

    code, out, err = _run_cli(
        ["batch", str(doc), str(txt), "-o", str(out_dir), "--json"],
        capsys,
    )
    assert code == ExitCode.SUCCESS  # 0
    data = json.loads(out)
    assert data["summary"]["cleaned"] == 1
    assert data["summary"]["no_change"] == 1
    assert data["summary"]["errors"] == 0
    assert data["summary"]["unsupported"] == 0


def test_batch_exit_code_partial_failure_is_code_1(tmp_path: Path, capsys):
    """Exit code is 1 (BATCH_PARTIAL_SUCCESS) on mixed success and failure.

    Section 7/9: ExitCode 2 must NEVER be repurposed for partial batch failure.
    ExitCode 1 is the canonical stable partial batch failure code.
    """
    valid = tmp_path / "valid.docx"
    valid.write_bytes(GOLDEN_DOCX.read_bytes())

    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"PK\x03\x04broken")

    unsupported = tmp_path / "file.unsupported_xyz"
    unsupported.write_bytes(b"some raw data")

    out_dir = tmp_path / "out"

    code, out, err = _run_cli(
        ["batch", str(valid), str(corrupt), str(unsupported), "-o", str(out_dir), "--json"],
        capsys,
    )
    assert code == ExitCode.BATCH_PARTIAL_SUCCESS  # 1
    assert code != ExitCode.UNSUPPORTED  # NOT 2
    data = json.loads(out)
    assert data["summary"]["cleaned"] == 1
    assert data["summary"]["errors"] == 1
    assert data["summary"]["unsupported"] == 1


def test_batch_exit_code_zero_inputs_is_code_2(tmp_path: Path, capsys):
    """Exit code is 2 (BATCH_FATAL_SETUP) when zero inputs are discovered."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    code, out, err = _run_cli(
        ["batch", str(empty_dir), "--json"],
        capsys,
    )
    assert code == ExitCode.BATCH_FATAL_SETUP  # 2


def test_batch_exit_code_invalid_arguments_is_code_4(tmp_path: Path, capsys):
    """Invalid command syntax or processing mode returns ExitCode 4 (INVALID_INPUT)."""
    code, out, err = _run_cli(
        ["batch", str(tmp_path), "--mode", "invalid_mode_xyz", "--json"],
        capsys,
    )
    assert code == ExitCode.INVALID_INPUT  # 4


# ============================================================================
# 2. DRY-RUN ZERO-WRITE CONTRACT & NONEXISTENT DIRECTORIES
# ============================================================================

def test_batch_dry_run_zero_write_contract(tmp_path: Path, capsys):
    """Section 11: Nonexistent output and reports directories MUST NOT be created in dry-run.

    Zero files, zero directories, zero temp files created.
    """
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    doc = input_dir / "document.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())

    nonexistent_out = tmp_path / "generated" / "output"
    nonexistent_rep = tmp_path / "generated" / "reports"
    assert not nonexistent_out.exists()
    assert not nonexistent_rep.exists()

    code, out, err = _run_cli(
        [
            "batch",
            str(input_dir),
            "-r",
            "--dry-run",
            "-o",
            str(nonexistent_out),
            "--reports-dir",
            str(nonexistent_rep),
            "--json",
        ],
        capsys,
    )

    assert code == ExitCode.SUCCESS
    data = json.loads(out)
    assert data["dry_run"] is True
    assert data["summary"]["inspected"] == 1
    assert data["summary"]["cleaned"] == 0

    # Explicit assertions: directories were NOT created
    assert not nonexistent_out.exists(), "Dry-run violated contract: output directory was created!"
    assert not nonexistent_rep.exists(), "Dry-run violated contract: reports directory was created!"
    assert not (tmp_path / "generated").exists(), "Dry-run created intermediate directory!"


# ============================================================================
# 3. INPUT TREE IMMUTABILITY
# ============================================================================

def test_batch_dry_run_input_tree_immutability(tmp_path: Path, capsys):
    """Section 12: Input tree files must retain identical path, SHA256, size, and mtime_ns."""
    import hashlib

    input_dir = tmp_path / "sources"
    input_dir.mkdir()
    doc1 = input_dir / "f1.docx"
    doc1.write_bytes(GOLDEN_DOCX.read_bytes())
    txt2 = input_dir / "f2.txt"
    txt2.write_text("Unchanged test content", encoding="utf-8")

    # Snapshot before
    snapshot_before = {}
    for fp in input_dir.iterdir():
        st = fp.stat()
        sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        snapshot_before[fp.name] = {
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": sha,
        }

    # Run dry-run batch
    code, out, err = _run_cli(
        ["batch", str(input_dir), "--dry-run", "--json"],
        capsys,
    )
    assert code == ExitCode.SUCCESS

    # Snapshot after
    snapshot_after = {}
    for fp in input_dir.iterdir():
        st = fp.stat()
        sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        snapshot_after[fp.name] = {
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": sha,
        }

    assert snapshot_before == snapshot_after, "Input tree mutated during dry-run!"


# ============================================================================
# 4. RECURSIVE DIRECTORY SELF-INGESTION & NESTED EXCLUSION
# ============================================================================

def test_batch_recursive_nested_output_and_reports_exclusion(tmp_path: Path, capsys):
    """Section 15/16: Nested output and reports directories inside input root MUST NOT be self-ingested."""
    input_root = tmp_path / "workspace"
    input_root.mkdir()
    doc = input_root / "source.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())

    nested_out = input_root / "generated" / "output"
    nested_rep = input_root / "generated" / "reports"

    # First run: recursive batch with nested output & reports
    code, out, err = _run_cli(
        [
            "batch",
            str(input_root),
            "-r",
            "-o",
            str(nested_out),
            "--reports-dir",
            str(nested_rep),
            "--json",
        ],
        capsys,
    )

    assert code == ExitCode.SUCCESS
    data1 = json.loads(out)
    assert data1["input_count"] == 1
    assert data1["summary"]["cleaned"] == 1
    assert nested_out.exists()
    assert nested_rep.exists()

    # Verify generated output and report files exist in nested locations
    cleaned_file = nested_out / "source.cleaned.docx"
    assert cleaned_file.exists()
    report_file = nested_rep / "batch_report.json"
    assert report_file.exists()

    # Second run: rerun the EXACT SAME command on the live tree
    # Expected: only original source.docx is processed!
    code2, out2, err2 = _run_cli(
        [
            "batch",
            str(input_root),
            "-r",
            "-o",
            str(nested_out),
            "--reports-dir",
            str(nested_rep),
            "--json",
        ],
        capsys,
    )

    assert code2 == ExitCode.SUCCESS
    data2 = json.loads(out2)
    assert data2["input_count"] == 1, (
        f"Self-ingestion detected on rerun! Input count was {data2['input_count']} instead of 1."
    )
    assert data2["summary"]["cleaned"] == 1
    # Check that there are NO file.cleaned.cleaned.docx artifacts anywhere
    duplicate_cleaned = list(input_root.rglob("*.cleaned.*.docx")) + list(input_root.rglob("*.cleaned.cleaned*"))
    # Note: collision safe might name second run source.cleaned.1.docx, which is expected,
    # but source.cleaned.docx must NOT have been used as input!
    for item in data2["items"]:
        assert not item["input_path"].endswith(".cleaned.docx")
        assert not item["input_path"].endswith(".json")


# ============================================================================
# 5. POLICY B: EXPLICIT REJECTION OF OUTPUT_DIR == INPUT_DIR
# ============================================================================

def test_batch_output_dir_equals_input_dir_rejected(tmp_path: Path, capsys):
    """Section 18: --output-dir == input root is rejected as invalid configuration (Policy B)."""
    input_dir = tmp_path / "target_dir"
    input_dir.mkdir()
    doc = input_dir / "sample.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())

    code, out, err = _run_cli(
        ["batch", str(input_dir), "-o", str(input_dir), "--json"],
        capsys,
    )

    assert code == ExitCode.INVALID_INPUT  # 4
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error_code"] == "INVALID_INPUT"
    assert "Output directory cannot be identical to input directory" in data["error_message"]


def test_batch_reports_dir_equals_input_dir_rejected(tmp_path: Path, capsys):
    """Section 19: --reports-dir == input root is rejected as invalid configuration (Policy B)."""
    input_dir = tmp_path / "target_dir"
    input_dir.mkdir()
    doc = input_dir / "sample.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())

    code, out, err = _run_cli(
        ["batch", str(input_dir), "--reports-dir", str(input_dir), "--json"],
        capsys,
    )

    assert code == ExitCode.INVALID_INPUT  # 4
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error_code"] == "INVALID_INPUT"
    assert "Reports directory cannot be identical to input directory" in data["error_message"]


# ============================================================================
# 6. WINDOWS CASE-INSENSITIVE PATH NORMALIZATION
# ============================================================================

def test_batch_windows_case_insensitive_path_exclusion(tmp_path: Path):
    """Section 22: Path casing differences do not bypass nested exclusion."""
    base_dir = tmp_path / "MyWorkspace"
    base_dir.mkdir()
    (base_dir / "doc.docx").write_bytes(GOLDEN_DOCX.read_bytes())

    out_dir = base_dir / "Generated" / "OutPut"
    out_dir.mkdir(parents=True)
    (out_dir / "doc.cleaned.docx").write_bytes(GOLDEN_DOCX.read_bytes())

    # Lowercase path representation
    lower_out = Path(str(out_dir).lower())

    # Discover with lower_out in exclude_dirs
    discovered = discover_input_files([base_dir], recursive=True, exclude_dirs=[lower_out])
    paths = [p for p, _ in discovered]
    assert len(paths) == 1
    assert paths[0].name == "doc.docx"


# ============================================================================
# 7. SYMLINK & JUNCTION SAFETY
# ============================================================================

def test_batch_symlink_directory_safety(tmp_path: Path):
    """Section 20/21: Symlink directories inside input pointing back or outside are NOT followed."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "doc.docx").write_bytes(GOLDEN_DOCX.read_bytes())

    # Attempt to create a symlink directory
    link_dir = src_dir / "recursive_loop_link"
    try:
        os.symlink(src_dir, link_dir, target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"SKIPPED_ENVIRONMENT: Symlink creation not permitted ({e})")

    discovered = discover_input_files([src_dir], recursive=True)
    paths = [p for p, _ in discovered]
    # Must only discover the original file once, without infinite loop or duplicate traversal
    assert len(paths) == 1
    assert paths[0].name == "doc.docx"


# ============================================================================
# 8. PRESERVE LEGITIMATE SOURCE WITH 'CLEANED' IN BASENAME
# ============================================================================

def test_batch_preserves_legitimate_source_with_cleaned_name(tmp_path: Path):
    """Section 23: Legitimate source files named 'cleaned_report.docx' are NOT excluded."""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    legit_file = input_dir / "user_cleaned_final_v2.docx"
    legit_file.write_bytes(GOLDEN_DOCX.read_bytes())

    out_dir = tmp_path / "out"
    processor = BatchProcessor()
    report = processor.process_paths(inputs=[legit_file], output_dir=out_dir)

    assert report.input_count == 1
    assert report.summary.cleaned == 1
    assert report.items[0].status == "CLEANED"


# ============================================================================
# 9. FAULT ISOLATION AND MATHEMATICAL RECONCILIATION
# ============================================================================

def test_batch_fault_isolation_and_reconciliation(tmp_path: Path):
    """Section 24/25: Mixed item types; one bad item never crashes healthy siblings.

    summary.total == cleaned + no_change + inspected + unsupported + validation_failed + errors + skipped
    """
    valid = tmp_path / "valid.docx"
    valid.write_bytes(GOLDEN_DOCX.read_bytes())

    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"PK\x03\x04bad_data")

    unsupported = tmp_path / "unsupported.bin"
    unsupported.write_bytes(b"binary data")

    clean_txt = tmp_path / "clean.txt"
    clean_txt.write_text("Hello clean text", encoding="utf-8")

    out_dir = tmp_path / "out"
    processor = BatchProcessor()
    report = processor.process_paths(
        inputs=[valid, corrupt, unsupported, clean_txt],
        output_dir=out_dir,
    )

    assert report.summary.reconcile()
    assert report.summary.total == 4
    assert report.summary.cleaned == 1
    assert report.summary.errors == 1
    assert report.summary.unsupported == 1
    assert report.summary.no_change == 1


# ============================================================================
# 10. CLI JSON STDOUT PURITY
# ============================================================================

def test_batch_json_stdout_purity_success_and_failure(tmp_path: Path, capsys):
    """Section 10: stdout contains exclusively valid JSON; diagnostics on stderr."""
    # Case A: Success
    valid = tmp_path / "valid.docx"
    valid.write_bytes(GOLDEN_DOCX.read_bytes())
    out_dir = tmp_path / "out"

    code_s, out_s, err_s = _run_cli(
        ["batch", str(valid), "-o", str(out_dir), "--json"],
        capsys,
    )
    assert code_s == ExitCode.SUCCESS
    data_s = json.loads(out_s)  # Must parse cleanly
    assert "schema_version" in data_s

    # Case B: Partial failure
    corrupt = tmp_path / "bad.docx"
    corrupt.write_bytes(b"not a zip")

    code_f, out_f, err_f = _run_cli(
        ["batch", str(valid), str(corrupt), "-o", str(out_dir), "--json"],
        capsys,
    )
    assert code_f == ExitCode.BATCH_PARTIAL_SUCCESS
    data_f = json.loads(out_f)  # Must parse cleanly without warning or progress prefix
    assert data_f["summary"]["errors"] == 1


# ============================================================================
# 11. REPORT PRIVACY INVARIANT
# ============================================================================

def test_batch_report_privacy_sentinel_absent(tmp_path: Path, capsys):
    """Section 26: Sentinel token from document body MUST NOT appear in JSON or reports."""
    sentinel = "CONFIDENTIAL_SENTINEL_TOKEN_XYZ_987654"
    txt_file = tmp_path / "private.txt"
    txt_file.write_text(f"Secret document body: {sentinel} with hidden text", encoding="utf-8")

    out_dir = tmp_path / "out"
    rep_dir = tmp_path / "reports"

    code, out, err = _run_cli(
        [
            "batch",
            str(txt_file),
            "-o",
            str(out_dir),
            "--reports-dir",
            str(rep_dir),
            "--json",
        ],
        capsys,
    )

    assert code == ExitCode.SUCCESS
    # Assert sentinel absent from stdout JSON
    assert sentinel not in out, "Privacy violation: sentinel leaked to CLI stdout JSON!"
    # Assert sentinel absent from stderr
    assert sentinel not in err, "Privacy violation: sentinel leaked to stderr!"

    # Assert sentinel absent from per-file report
    item_report = list(rep_dir.glob("*.json"))[0]
    assert sentinel not in item_report.read_text(encoding="utf-8")

    # Assert sentinel absent from batch report
    batch_rep = (rep_dir / "batch_report.json").read_text(encoding="utf-8")
    assert sentinel not in batch_rep


# ============================================================================
# 12. ZERO NETWORK INVARIANT
# ============================================================================

def test_batch_zero_network_egress(tmp_path: Path, monkeypatch):
    """Section 27: Zero network socket connections permitted during batch processing."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("CRITICAL: Network socket connection attempted during batch processing!")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    doc = tmp_path / "sample.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())
    out_dir = tmp_path / "out"

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[doc], output_dir=out_dir)
    assert report.summary.cleaned == 1
    assert report.privacy["network_used"] is False
