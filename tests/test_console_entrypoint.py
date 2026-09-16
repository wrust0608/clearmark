"""Smoke tests for the packaged 'watermarks' console entry point.

Proves:
1. Console entry point registration in package metadata ([project.scripts] watermarks = "service.scripts.cli:main").
2. Real command execution via 'uv run watermarks ...'.
3. Pure JSON stdout discipline through the packaged entrypoint wrapper.
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CANDIDATE_DOCX = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"


def test_console_entry_point_metadata():
    """Verify that 'watermarks' is registered as a project console script entry point."""
    eps = importlib.metadata.entry_points(group="console_scripts")
    watermarks_ep = [ep for ep in eps if ep.name == "watermarks"]
    assert len(watermarks_ep) == 1, f"Expected 1 'watermarks' console script entry point, found {watermarks_ep}"
    assert watermarks_ep[0].value == "service.scripts.cli:main"


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


def test_watermarks_cli_help():
    """Test 'watermarks --help' via registered console entry point."""
    proc = _exec_watermarks(["--help"])
    assert proc.returncode == 0
    assert "usage: watermarks" in proc.stdout
    assert "inspect" in proc.stdout
    assert "clean" in proc.stdout
    assert "verify" in proc.stdout
    assert "capabilities" in proc.stdout


def test_watermarks_cli_inspect_json():
    """Test 'watermarks inspect ... --json' stdout purity through console entry point."""
    proc = _exec_watermarks(["inspect", str(GOLDEN_DOCX), "--json"])
    assert proc.returncode == 0

    # stdout must parse cleanly with json.loads() with zero extra prose
    data = json.loads(proc.stdout)
    assert data["status"] == "INSPECTED"
    assert data["input"]["filename"] == "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
    assert data["input"]["format"] == "docx"
    assert data["input"]["sha256"] == "c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d"


def test_watermarks_cli_clean_dry_run_json():
    """Test 'watermarks clean ... --dry-run --json' stdout purity through console entry point."""
    proc = _exec_watermarks(["clean", str(GOLDEN_DOCX), "--dry-run", "--json"])
    assert proc.returncode == 0

    data = json.loads(proc.stdout)
    assert data["status"] == "INSPECTED"
    assert data["output"]["changed"] is False
    assert data["output"]["would_change"] is True
    assert len(data["mutation_plan"]["mutations"]) > 0


def test_watermarks_cli_verify_json():
    """Test 'watermarks verify ... --json' stdout purity through console entry point."""
    proc = _exec_watermarks(["verify", str(GOLDEN_DOCX), str(CANDIDATE_DOCX), "--json"])
    assert proc.returncode == 0

    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert data["status"] == "PASS"
    assert data["format"] == "docx"
    assert data["validation"]["structural_invariants_passed"] is True
    assert len(data["invariants"]) >= 5


def test_watermarks_cli_verify_unsupported_format(tmp_path: Path):
    """Test 'watermarks verify' with non-DOCX files returns UNSUPPORTED (exit code 2)."""
    orig = tmp_path / "orig.txt"
    orig.write_text("orig text", encoding="utf-8")
    cand = tmp_path / "cand.txt"
    cand.write_text("cand text", encoding="utf-8")

    proc = _exec_watermarks(["verify", str(orig), str(cand), "--json"])
    assert proc.returncode == 2

    data = json.loads(proc.stdout)
    assert data["ok"] is False
    assert data["status"] == "UNSUPPORTED"
    assert data["error_code"] == "UNSUPPORTED_VERIFICATION_CAPABILITY"
    assert "Verification capability is currently supported only for docx" in data["error_message"]


def test_watermarks_cli_capabilities_json():
    """Test 'watermarks capabilities --json' stdout purity through console entry point."""
    proc = _exec_watermarks(["capabilities", "--json"])
    assert proc.returncode == 0

    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert data["source"] == "service/scripts/format_policy.py"
    assert "docx" in data["formats"]
    assert "structural_invariants" in data["formats"]["docx"]["verify_capabilities"]
