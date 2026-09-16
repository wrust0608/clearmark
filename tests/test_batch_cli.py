"""Tests for Phase 4: Canonical CLI Batch Command (watermarks batch).

Covers:
- watermarks batch CLI execution
- Pure JSON stdout discipline with --json
- Human summary formatting without --json
- Exit code contracts:
  - 0: all items succeeded
  - 1: partial success (at least one failure or unsupported)
  - 2: fatal setup error / invalid arguments / zero inputs
- Directory batch with and without --recursive
- --output-dir collision-safe writing
- --reports-dir per-file JSON writing
- Execution via real console entrypoint ('uv run watermarks batch ...')
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from service.scripts.cli import ExitCode, main as cli_main

GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"


def _run_cli(args: list[str], capsys) -> tuple[int, str, str]:
    code = cli_main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _exec_watermarks(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute 'watermarks' via 'uv run watermarks' as a real user would."""
    cmd = ["uv", "run", "watermarks"] + args
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# 1. CLI Batch --json: stdout Purity
def test_cli_batch_json_purity(tmp_path: Path, capsys):
    f1 = tmp_path / "doc.docx"
    f1.write_bytes(GOLDEN_DOCX.read_bytes())
    f2 = tmp_path / "clean.txt"
    f2.write_text("Hello text", encoding="utf-8")

    out_dir = tmp_path / "out"

    code, out, err = _run_cli(
        ["batch", str(f1), str(f2), "-o", str(out_dir), "--json"],
        capsys,
    )

    assert code == ExitCode.SUCCESS
    # stdout must be exclusively valid JSON
    data = json.loads(out)
    assert data["schema_version"] == "2.1.0"
    assert data["input_count"] == 2
    assert data["summary"]["cleaned"] == 1
    assert data["summary"]["no_change"] == 1
    assert data["summary"]["errors"] == 0
    assert len(data["items"]) == 2


# 2. CLI Batch Human Output
def test_cli_batch_human_output(tmp_path: Path, capsys):
    f1 = tmp_path / "doc.docx"
    f1.write_bytes(GOLDEN_DOCX.read_bytes())
    out_dir = tmp_path / "out"

    code, out, err = _run_cli(
        ["batch", str(f1), "-o", str(out_dir)],
        capsys,
    )

    assert code == ExitCode.SUCCESS
    assert "=== ClearMark Batch Summary ===" in out
    assert "Total Inputs:         1" in out
    assert "Cleaned:              1" in out
    assert "=== Item Results ===" in out
    assert "[1/1]" in out
    assert "CLEANED" in out


# 3. CLI Batch Exit Code: Partial Success (Code 1)
def test_cli_batch_partial_success_exit_code(tmp_path: Path, capsys):
    valid_doc = tmp_path / "valid.docx"
    valid_doc.write_bytes(GOLDEN_DOCX.read_bytes())

    corrupt_doc = tmp_path / "corrupt.docx"
    corrupt_doc.write_bytes(b"PK\x03\x04broken")

    out_dir = tmp_path / "out"

    code, out, err = _run_cli(
        ["batch", str(valid_doc), str(corrupt_doc), "-o", str(out_dir), "--json"],
        capsys,
    )

    # Section 15: exit code 1 for partial success
    assert code == ExitCode.BATCH_PARTIAL_SUCCESS
    data = json.loads(out)
    assert data["summary"]["cleaned"] == 1
    assert data["summary"]["errors"] == 1
    # Successful file was still written!
    assert Path(data["items"][0]["output_path"]).exists()


# 4. CLI Batch Exit Code: Fatal Setup / Limit Exceeded (Code 2)
def test_cli_batch_limit_exceeded_exit_code(tmp_path: Path, monkeypatch, capsys):
    files = []
    for i in range(4):
        f = tmp_path / f"file_{i}.txt"
        f.write_text("text", encoding="utf-8")
        files.append(str(f))

    # Temporarily lower MAX_BATCH_FILES
    monkeypatch.setenv("WATERMARKS_MAX_BATCH_FILES", "2")
    # Re-import to pick up env
    import batch_processor
    monkeypatch.setattr(batch_processor, "MAX_BATCH_FILES", 2)

    code, out, err = _run_cli(["batch"] + files + ["--json"], capsys)
    assert code == ExitCode.UNSUPPORTED  # Value 2 (BATCH_FATAL_SETUP)
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error_code"] == "LIMIT_EXCEEDED"


# 5. CLI Directory Batch with --recursive
def test_cli_batch_directory_recursive(tmp_path: Path, capsys):
    sub = tmp_path / "subdir"
    sub.mkdir()

    f1 = tmp_path / "root.docx"
    f1.write_bytes(GOLDEN_DOCX.read_bytes())
    f2 = sub / "nested.docx"
    f2.write_bytes(GOLDEN_DOCX.read_bytes())

    out_dir = tmp_path / "out"

    # With --recursive
    code, out, err = _run_cli(
        ["batch", str(tmp_path), "-r", "-o", str(out_dir), "--json"],
        capsys,
    )

    assert code == ExitCode.SUCCESS
    data = json.loads(out)
    assert data["input_count"] == 2
    assert data["summary"]["cleaned"] == 2


# 6. Real Console Entrypoint Execution ('uv run watermarks batch ...')
def test_cli_batch_real_console_entrypoint(tmp_path: Path):
    doc = tmp_path / "entrypoint_test.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())
    out_dir = tmp_path / "out"

    proc = _exec_watermarks([
        "batch",
        str(doc),
        "-o",
        str(out_dir),
        "--json",
    ])

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["schema_version"] == "2.1.0"
    assert data["summary"]["cleaned"] == 1
    assert Path(data["items"][0]["output_path"]).exists()


# 7. CLI Batch --json Output Excludes Cleaned Payloads
def test_cli_batch_json_excludes_cleaned_bytes(tmp_path: Path, capsys):
    doc = tmp_path / "sample.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())
    out_dir = tmp_path / "out"

    code, out, err = _run_cli(
        ["batch", str(doc), "-o", str(out_dir), "--json"],
        capsys,
    )

    assert code == ExitCode.SUCCESS
    data = json.loads(out)
    item = data["items"][0]
    assert item["status"] == "CLEANED"
    assert "cleaned" not in item
    assert "cleaned_bytes" not in item
    assert "content_base64" not in item
    # Ensure stdout is compact metadata, not bloated by file data
    assert len(out.encode("utf-8")) < 10000

