"""tests/test_release_evidence.py

Unit tests for Phase 13 Release Evidence Automation (tools/build_release_evidence.py).
Tests helpers, parsers, validators, manifests, privacy scrubbing, and zero-network enforcement.
Runs fast without recursive pytest overhead.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import pytest

from tools.build_release_evidence import (
    REPO_ROOT,
    SCHEMA_VERSION,
    TARGET_RELEASE,
    sanitize_string,
    to_relative_path,
    parse_pytest_summary,
    get_capabilities_info,
    get_limits_info,
    get_contracts_info,
    verify_cross_contract_assertions,
    verify_frozen_core,
    verify_fixture_hashes,
    get_performance_evidence,
    get_security_evidence,
    get_privacy_evidence,
    get_idempotence_evidence,
    get_documentation_evidence,
    get_phase_provenance,
    validate_release_evidence,
    publish_bundle_atomically,
    generate_markdown_summary,
)


# ============================================================================
# 1. PYTEST OUTPUT PARSER TESTS
# ============================================================================

def test_pytest_output_parser_normal():
    sample = (
        "tests/test_foo.py ...\n"
        "tests/test_bar.py ..\n"
        "================ 1952 passed, 152 skipped in 198.43s (0:03:18) ================\n"
    )
    res = parse_pytest_summary(sample, returncode=0)
    assert res["success"] is True
    assert res["passed"] == 1952
    assert res["skipped"] == 152
    assert res["failed"] == 0
    assert res["errors"] == 0
    assert res["warnings"] == 0
    assert res["duration_seconds"] == 198.43


def test_pytest_output_parser_with_failures_and_warnings():
    sample = (
        "FAILURES\n"
        "____ test_something ____\n"
        "assert False\n"
        "================ 2 failed, 15 passed, 1 warning in 1.45s ================\n"
    )
    res = parse_pytest_summary(sample, returncode=1)
    assert res["success"] is False
    assert res["passed"] == 15
    assert res["failed"] == 2
    assert res["warnings"] == 1
    assert res["duration_seconds"] == 1.45


def test_pytest_output_parser_with_errors_and_xpassed():
    sample = (
        "================ 1 error, 10 passed, 1 xfailed, 1 xpassed in 3.12s ================\n"
    )
    res = parse_pytest_summary(sample, returncode=1)
    assert res["success"] is False
    assert res["errors"] == 1
    assert res["passed"] == 10
    assert res["xfailed"] == 1
    assert res["xpassed"] == 1
    assert res["duration_seconds"] == 3.12


# ============================================================================
# 2. PRIVACY SCRUB & RELATIVE PATH TESTS
# ============================================================================

def test_privacy_scrub_and_relative_paths():
    sample = f"Error in {REPO_ROOT}\\service\\scripts\\file.py: user path was leaked"
    sanitized = sanitize_string(sample, REPO_ROOT)
    assert str(REPO_ROOT) not in sanitized
    assert "./service/scripts/file.py" in sanitized or ".\\service" in sanitized or "./" in sanitized

    rel = to_relative_path(REPO_ROOT / "docs" / "capabilities.md", REPO_ROOT)
    assert rel == "docs/capabilities.md"
    assert "\\" not in rel


# ============================================================================
# 3. CAPABILITY EXTRACTION & PARITY
# ============================================================================

def test_capability_extraction_and_parity():
    caps = get_capabilities_info()
    assert caps["canonical_policy_count"] == 23
    assert caps["total_registered_extensions"] == 37
    assert caps["extension_aliases_count"] == 14
    assert caps["runtime_available_count"] == 22
    assert caps["dependency_sensitive_policies"] == ["pdf"]
    assert "docx" in caps["verify_supported_policies"]
    assert "xlsx" in caps["verify_supported_policies"]
    assert "pptx" in caps["verify_supported_policies"]
    assert caps["safe_only_policies"] == ["svg"]
    assert caps["server_capabilities_parity"] is True


# ============================================================================
# 4. LIMIT EXTRACTION AGAINST PRODUCTION CONSTANTS
# ============================================================================

def test_limit_extraction_against_production_constants():
    limits_info = get_limits_info()
    assert limits_info["status"] == "PASS"
    lims = limits_info["limits"]

    # Verify key constants are present
    assert "common.MAX_INPUT_BYTES" in lims
    assert "server.MAX_INPUT_BYTES" in lims
    assert "batch_processor.MAX_BATCH_FILES" in lims
    assert "security.SecurityLimits.max_member_count" in lims

    dist = limits_info["batch_cli_vs_http_distinction"]
    assert dist["cli_max_batch_files"] == 100
    assert dist["http_max_batch_files"] == 50


# ============================================================================
# 5. CONTRACT & HTTP STATUS MAPPINGS
# ============================================================================

def test_contract_and_http_status_mapping():
    contracts = get_contracts_info()
    assert contracts["status"] == "PASS"
    exits = contracts["exit_codes"]
    assert exits["SUCCESS"] == 0
    assert exits["UNSUPPORTED"] == 2
    assert exits["VALIDATION_FAILED"] == 3
    assert exits["INVALID_INPUT"] == 4
    assert exits["DEPENDENCY_MISSING"] == 5
    assert exits["LIMIT_EXCEEDED"] == 6
    assert exits["BATCH_PARTIAL_FAILURE"] == 7
    assert exits["BATCH_PARTIAL_SUCCESS"] == 7
    assert exits["INTERNAL_ERROR"] == 10

    http_map = contracts["http_status_mappings"]
    assert http_map["UNSUPPORTED_FORMAT"] == 415
    assert http_map["INVALID_CONTAINER"] == 400
    assert http_map["VALIDATION_FAILED"] == 422
    assert http_map["OPTIONAL_DEPENDENCY_MISSING"] == 424
    assert http_map["UNSUPPORTED_ARCHIVE_FEATURE"] == 422
    assert http_map["PROCESSING_LIMIT_EXCEEDED"] == 413
    assert http_map["INTERNAL_ERROR"] == 500


def test_cross_contract_assertions():
    errors = verify_cross_contract_assertions()
    assert len(errors) == 0, f"Cross-contract assertion failures: {errors}"


# ============================================================================
# 6. FROZEN CORE & FIXTURE HASHES
# ============================================================================

def test_frozen_core_diff_and_fixture_hashes():
    core = verify_frozen_core(REPO_ROOT)
    assert core["status"] == "PASS"
    assert core["diff_empty"] is True

    hashes = verify_fixture_hashes(REPO_ROOT)
    assert hashes["status"] == "PASS"
    assert hashes["golden_docx"]["match"] is True
    assert hashes["candidate_docx"]["match"] is True


# ============================================================================
# 7. PHASE PROVENANCE EXTRACTION
# ============================================================================

def test_phase_provenance():
    prov = get_phase_provenance(REPO_ROOT)
    assert prov["status"] == "PASS"
    phases = prov["phases"]
    assert "phase_4" in phases
    assert phases["phase_4"]["canonical_commit_verified"] is True
    assert "phase_12" in phases
    assert phases["phase_12"]["canonical_commit_verified"] is True


# ============================================================================
# 8. MANIFEST HASHING & SELF-HASH RULE
# ============================================================================

def test_manifest_and_bundle_validation():
    with tempfile.TemporaryDirectory() as td:
        bundle_dir = Path(td)

        dummy_evidence = {
            "schema_version": SCHEMA_VERSION,
            "target_release": TARGET_RELEASE,
            "generated_at_utc": "2026-09-17T12:00:00Z",
            "mode": "quick",
            "overall_status": "PASS",
            "release_ready": False,
            "git": {"head": "abc", "branch": "v2.1-dev", "is_clean": True},
            "capabilities": {},
            "limits": {},
            "contracts": {},
            "security": {},
            "privacy": {},
            "idempotence": {},
            "performance": {},
            "documentation": {},
            "tests": {"suites": {}},
            "frozen_core": {},
            "hashes": {},
        }

        # Write release_evidence.json
        ev_file = bundle_dir / "release_evidence.json"
        ev_file.write_text(json.dumps(dummy_evidence, indent=2), encoding="utf-8")

        # Create dummy companion file
        comp_file = bundle_dir / "TEST_RESULTS.json"
        comp_file.write_text("{}", encoding="utf-8")

        # Create MANIFEST.json (must NOT include MANIFEST.json or MANIFEST.sha256)
        manifest_files = []
        for f in sorted(bundle_dir.iterdir()):
            if f.name not in ("MANIFEST.json", "MANIFEST.sha256"):
                manifest_files.append({
                    "path": f.name,
                    "size_bytes": len(f.read_bytes()),
                    "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                    "purpose": "test artifact",
                    "schema_version": SCHEMA_VERSION,
                })

        manifest_data = {
            "schema_version": SCHEMA_VERSION,
            "target_release": TARGET_RELEASE,
            "generated_at_utc": "2026-09-17T12:00:00Z",
            "file_count": len(manifest_files),
            "files": manifest_files,
        }
        manifest_bytes = (json.dumps(manifest_data, indent=2, sort_keys=True) + "\n").encode("utf-8")
        manifest_file = bundle_dir / "MANIFEST.json"
        manifest_file.write_bytes(manifest_bytes)

        # Write MANIFEST.sha256
        m_sha = hashlib.sha256(manifest_bytes).hexdigest()
        (bundle_dir / "MANIFEST.sha256").write_text(f"{m_sha}  MANIFEST.json\n", encoding="utf-8")

        # Validate
        valid, errors = validate_release_evidence(bundle_dir)
        assert valid is True, f"Validation failed: {errors}"
        assert len(errors) == 0


# ============================================================================
# 9. ATOMIC PUBLISH & FAILURE ISOLATION
# ============================================================================

def test_atomic_publish_and_failure_isolation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        staging = root / "staging"
        target = root / "published"

        staging.mkdir()
        (staging / "file1.txt").write_text("content1", encoding="utf-8")

        publish_bundle_atomically(staging, target)
        assert target.exists()
        assert (target / "file1.txt").read_text(encoding="utf-8") == "content1"
        assert not staging.exists()

        # Update target atomically
        staging2 = root / "staging2"
        staging2.mkdir()
        (staging2 / "file1.txt").write_text("updated", encoding="utf-8")

        publish_bundle_atomically(staging2, target)
        assert (target / "file1.txt").read_text(encoding="utf-8") == "updated"


# ============================================================================
# 10. ZERO NETWORK ENFORCEMENT
# ============================================================================

def test_zero_network_enforcement(monkeypatch):
    """Assert release evidence helper functions make zero network socket calls."""
    def _prohibited_socket(*args, **kwargs):
        raise RuntimeError("Network egress prohibited in release evidence builder")

    monkeypatch.setattr(socket, "socket", _prohibited_socket)
    monkeypatch.setattr(socket, "create_connection", _prohibited_socket)

    # Calling extractors must not trigger any socket calls
    caps = get_capabilities_info()
    assert caps["canonical_policy_count"] == 23

    lims = get_limits_info()
    assert lims["status"] == "PASS"

    contracts = get_contracts_info()
    assert contracts["status"] == "PASS"


# ============================================================================
# 11. SUBPROCESS TIMEOUT & FAILURE HANDLING
# ============================================================================

def test_run_test_suite_timeout():
    """Verify run_test_suite cleanly captures command timeout without hanging."""
    from tools.build_release_evidence import run_test_suite
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    res = run_test_suite(cmd, cwd=REPO_ROOT, timeout=0.2)
    assert res["success"] is False
    assert res.get("timeout") is True
    assert res["errors"] == 1


def test_run_test_suite_failure():
    """Verify run_test_suite captures nonzero exit code and failures."""
    from tools.build_release_evidence import run_test_suite
    cmd = [sys.executable, "-c", "import sys; print('FAILED TEST EXCERPT'); sys.exit(1)"]
    res = run_test_suite(cmd, cwd=REPO_ROOT, timeout=5.0)
    assert res["success"] is False
    assert res["returncode"] == 1
    assert "diagnostic_excerpt" in res


def test_markdown_summary_generation():
    """Verify generate_markdown_summary outputs expected headings and sections."""
    dummy_ev = {
        "generated_at_utc": "2026-09-17T12:00:00Z",
        "schema_version": SCHEMA_VERSION,
        "target_release": TARGET_RELEASE,
        "mode": "quick",
        "overall_status": "PASS",
        "release_ready": False,
        "git": {"head": "123456", "branch": "v2.1-dev", "is_clean": True, "base_commit_v200": "abcdef"},
        "frozen_core": {"diff_empty": True},
        "hashes": {"fixtures": {"golden_docx": {"match": True}, "candidate_docx": {"match": True}}},
        "capabilities": {"canonical_policy_count": 23, "total_registered_extensions": 37, "extension_aliases_count": 14, "runtime_available_count": 22, "dependency_sensitive_policies": ["pdf"], "verify_supported_policies": ["docx", "xlsx", "pptx"]},
        "tests": {"suites": {"suite_a": {"success": True, "passed": 10, "skipped": 0, "failed": 0, "duration_seconds": 1.2}}},
    }
    md = generate_markdown_summary(dummy_ev)
    assert "# ClearMark v2.1 Release Evidence Report" in md
    assert "## 1. Git Repository State" in md
    assert "## 2. Frozen Core Integrity" in md
    assert "## 3. Format Capabilities Summary" in md
    assert "## 4. Test Verification Suites" in md
    assert "Zero Network Egress" in md

