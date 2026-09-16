"""Tests for Phase 3: Legacy CLI Backward Compatibility & Policy Forwarder Audit.

Covers:
- service/scripts/clean_file.py legacy invocation & deprecation notice to stderr
- service/scripts/inspect_file.py legacy invocation & deprecation notice to stderr
- --json stdout purity (deprecation warnings must never corrupt stdout)
- ADR-010 policy forwarder deprecation warning in pipeline_types.__getattr__
"""

from __future__ import annotations

import json
import subprocess
import sys
import warnings
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CLEAN_FILE_PY = REPO_ROOT / "service" / "scripts" / "clean_file.py"
INSPECT_FILE_PY = REPO_ROOT / "service" / "scripts" / "inspect_file.py"


def _run_script(script: Path, args: list[str]) -> tuple[int, str, str]:
    cmd = [sys.executable, str(script)] + args
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    return res.returncode, res.stdout, res.stderr


# 1. clean_file.py backward compatibility & deprecation
def test_clean_file_legacy_invocation_and_deprecation(tmp_path: Path):
    target = tmp_path / "doc.docx"
    target.write_bytes(GOLDEN_DOCX.read_bytes())
    out_target = tmp_path / "doc_out.docx"

    code, stdout, stderr = _run_script(CLEAN_FILE_PY, [str(target), "-o", str(out_target)])
    assert code == 0
    assert out_target.exists()

    # Deprecation warning on stderr identifying canonical replacement
    assert "DEPRECATION" in stderr
    assert "watermarks clean" in stderr


def test_clean_file_json_stdout_purity(tmp_path: Path):
    target = tmp_path / "doc.docx"
    target.write_bytes(GOLDEN_DOCX.read_bytes())
    out_target = tmp_path / "doc_out.docx"

    code, stdout, stderr = _run_script(CLEAN_FILE_PY, [str(target), "-o", str(out_target), "--json"])
    assert code == 0

    # stdout must be valid JSON parseable directly by json.loads
    data = json.loads(stdout)
    assert isinstance(data, dict)

    # Deprecation warning must be on stderr only, never contaminating stdout
    assert "DEPRECATION" in stderr
    assert "DEPRECATION" not in stdout


# 2. inspect_file.py backward compatibility & deprecation
def test_inspect_file_legacy_invocation_and_deprecation(tmp_path: Path):
    target = tmp_path / "doc.docx"
    target.write_bytes(GOLDEN_DOCX.read_bytes())

    code, stdout, stderr = _run_script(INSPECT_FILE_PY, [str(target)])
    assert code == 0

    # Deprecation warning on stderr identifying canonical replacement
    assert "DEPRECATION" in stderr
    assert "watermarks inspect" in stderr


def test_inspect_file_json_stdout_purity(tmp_path: Path):
    target = tmp_path / "doc.docx"
    target.write_bytes(GOLDEN_DOCX.read_bytes())

    code, stdout, stderr = _run_script(INSPECT_FILE_PY, [str(target), "--json"])
    assert code == 0

    # stdout must parse cleanly as JSON
    data = json.loads(stdout)
    assert isinstance(data, dict)

    # Deprecation warning on stderr only
    assert "DEPRECATION" in stderr
    assert "DEPRECATION" not in stdout


# 3. ADR-010 Policy Forwarder Deprecation (Section 7)
def test_pipeline_types_policy_forwarder_deprecation():
    import service.scripts.pipeline_types as pt

    with pytest.deprecated_call(match="Importing FormatPolicyRegistry from pipeline_types is deprecated"):
        _ = pt.FormatPolicyRegistry

    with pytest.deprecated_call(match="Importing FormatPolicy from pipeline_types is deprecated"):
        _ = pt.FormatPolicy
