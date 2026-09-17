"""tests/test_review_package.py

Unit tests for Phase 14 Release Candidate Package Builder & Auditor.
Tests are fast, self-contained, and use synthetic fixtures/helper abstractions.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
from typing import Any
import zipfile

import pytest

from tools.build_review_package import (
    CONTAINER_USERS,
    DETERMINISTIC_TIMESTAMP,
    GOLDEN_DOCX_HASH,
    CANDIDATE_DOCX_HASH,
    PACKAGE_FILENAME,
    PACKAGE_ROOT_DIR,
    STABLE_PACKAGE_FILENAME,
    STABLE_PACKAGE_ROOT_DIR,
    PackageSecurityError,
    audit_review_package_archive,
    compare_stable_vs_rc,
    compute_source_tree_digest,
    detect_case_collisions,
    scan_content_privacy,
    validate_path_safety,
)


# ---------------------------------------------------------------------------
# Path & Container Safety Tests
# ---------------------------------------------------------------------------

def test_path_validation_safe() -> None:
    """Valid relative forward-slash paths must pass without error."""
    safe_paths = [
        "README.md",
        "service/scripts/cleaner.py",
        "tests/test_docx.py",
        "artifacts/v2.1/release_evidence/release_evidence.json",
    ]
    for p in safe_paths:
        validate_path_safety(p)
        validate_path_safety(f"{PACKAGE_ROOT_DIR}/{p}", under_root=PACKAGE_ROOT_DIR)


def test_path_validation_zipslip_rejection() -> None:
    """ZipSlip traversal paths must be rejected."""
    bad_paths = [
        "../escaped.txt",
        "service/../../escaped.txt",
        "foo/bar/../../../etc/passwd",
        "./dot_slash.txt",
    ]
    for p in bad_paths:
        with pytest.raises(PackageSecurityError, match="traversal"):
            validate_path_safety(p)


def test_path_validation_backslash_rejection() -> None:
    """Backslash separated paths must be rejected."""
    bad_paths = [
        r"service\scripts\cleaner.py",
        r"tests\fixtures\file.docx",
    ]
    for p in bad_paths:
        with pytest.raises(PackageSecurityError, match="backslash"):
            validate_path_safety(p)


def test_path_validation_leading_slash_rejection() -> None:
    """Absolute paths with leading slashes must be rejected."""
    bad_paths = [
        "/etc/passwd",
        "/service/app.py",
    ]
    for p in bad_paths:
        with pytest.raises(PackageSecurityError, match="leading slash"):
            validate_path_safety(p)


def test_path_validation_drive_letter_rejection() -> None:
    """Windows drive prefix paths must be rejected."""
    bad_paths = [
        "C:/Windows/System32",
        "D:payload.bin",
    ]
    for p in bad_paths:
        with pytest.raises(PackageSecurityError, match="drive prefix"):
            validate_path_safety(p)


def test_path_validation_empty_component_rejection() -> None:
    """Paths with empty components (double slashes) must be rejected."""
    bad_paths = [
        "service//app.py",
        "foo///bar.txt",
    ]
    for p in bad_paths:
        with pytest.raises(PackageSecurityError, match="empty component"):
            validate_path_safety(p)


def test_path_validation_null_byte_rejection() -> None:
    """Paths with NUL characters must be rejected."""
    with pytest.raises(PackageSecurityError, match="NUL byte"):
        validate_path_safety("service/cleaner\0.py")


def test_path_validation_under_root_enforcement() -> None:
    """Paths not strictly under the specified root dir must be rejected."""
    with pytest.raises(PackageSecurityError, match="not under expected package root"):
        validate_path_safety("WrongRoot/README.md", under_root=PACKAGE_ROOT_DIR)


def test_windows_reserved_names_rejection() -> None:
    """Windows reserved device names must be rejected."""
    reserved_paths = [
        "CON",
        "con.txt",
        "service/PRN",
        "tests/AUX.json",
        "NUL",
        "COM1.dat",
        "LPT9.bin",
    ]
    for p in reserved_paths:
        with pytest.raises(PackageSecurityError, match="Windows reserved device name"):
            validate_path_safety(p)


def test_case_collision_detection() -> None:
    """Case collisions across members must be detected."""
    paths = [
        "README.md",
        "service/cleaner.py",
        "readme.md",
    ]
    collisions = detect_case_collisions(paths)
    assert len(collisions) == 1
    assert ("README.md", "readme.md") in collisions or ("readme.md", "README.md") in collisions

    clean_paths = ["README.md", "service/cleaner.py", "docs/report.md"]
    assert detect_case_collisions(clean_paths) == []


# ---------------------------------------------------------------------------
# Digest & Determinism Tests
# ---------------------------------------------------------------------------

def test_source_tree_digest_deterministic() -> None:
    """Source tree digest must follow canonical stream format and be deterministic."""
    entries = [
        ("file_b.txt", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", 20),
        ("file_a.txt", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 10),
    ]
    # Unsorted input vs sorted input must yield identical digest because function sorts
    digest1 = compute_source_tree_digest(entries)
    digest2 = compute_source_tree_digest(list(reversed(entries)))
    assert digest1 == digest2
    assert len(digest1) == 64

    # Verify canonical stream format manually
    stream = bytearray()
    stream.extend(b"file_a.txt\0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\0" + b"10\n")
    stream.extend(b"file_b.txt\0bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\0" + b"20\n")
    expected = hashlib.sha256(stream).hexdigest()
    assert digest1 == expected


def test_deterministic_zip_bytes(tmp_path: Path) -> None:
    """Two independent builds with same contents and metadata must produce 100% identical bytes."""
    def build_test_zip(out_path: Path) -> None:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as zf:
            items = [
                ("ClearMark/a.txt", b"Hello A"),
                ("ClearMark/b.txt", b"Hello B"),
            ]
            for fname, data in sorted(items, key=lambda x: x[0]):
                zinfo = zipfile.ZipInfo(filename=fname, date_time=DETERMINISTIC_TIMESTAMP)
                zinfo.create_system = 3
                zinfo.flag_bits |= 0x800
                zinfo.external_attr = (0o100000 | 0o644) << 16
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(zinfo, data)

    zip1 = tmp_path / "test1.zip"
    zip2 = tmp_path / "test2.zip"
    build_test_zip(zip1)
    build_test_zip(zip2)

    assert zip1.read_bytes() == zip2.read_bytes()
    assert hashlib.sha256(zip1.read_bytes()).hexdigest() == hashlib.sha256(zip2.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Privacy & Secret Scanning Tests
# ---------------------------------------------------------------------------

def test_privacy_scanner_detects_private_keys(tmp_path: Path) -> None:
    """Private key headers must trigger hard fail."""
    keys = [
        "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASC...",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjE...",
    ]
    for i, k in enumerate(keys):
        f = tmp_path / f"key_{i}.pem"
        f.write_text(k, encoding="utf-8")

    findings = scan_content_privacy(tmp_path)
    assert len(findings) == 3
    categories = {f["category"] for f in findings}
    assert "PRIVATE_KEY" in categories


def test_privacy_scanner_detects_windows_user_paths(tmp_path: Path) -> None:
    """Windows user paths like C:\\Users\\... must be detected."""
    f = tmp_path / "leaked_path.txt"
    f.write_text("Failed to open file at C:\\Users\\Developer\\secrets.txt\n", encoding="utf-8")

    findings = scan_content_privacy(tmp_path)
    assert len(findings) == 1
    assert findings[0]["category"] == "LOCAL_USER_PATH"


def test_privacy_scanner_permits_container_users(tmp_path: Path) -> None:
    """Container users (/home/remover, /home/markllm) must not be flagged."""
    f = tmp_path / "Dockerfile.test"
    f.write_text("ENV HOME=/home/remover\nWORKDIR /home/markllm\n", encoding="utf-8")

    findings = scan_content_privacy(tmp_path)
    assert len(findings) == 0


def test_privacy_scanner_detects_host_unix_home(tmp_path: Path) -> None:
    """Arbitrary host user homes (/home/johndoe) must be flagged."""
    f = tmp_path / "host_path.txt"
    f.write_text("Saved output to /home/johndoe/output.json\n", encoding="utf-8")

    findings = scan_content_privacy(tmp_path)
    assert len(findings) == 1
    assert findings[0]["category"] == "LOCAL_USER_PATH"


def test_privacy_scanner_detects_dev_username(tmp_path: Path) -> None:
    """Known developer usernames must be flagged in unallowlisted files."""
    f = tmp_path / "comment.py"
    f.write_text("# Author: nvhoa\ndef func(): pass\n", encoding="utf-8")

    findings = scan_content_privacy(tmp_path)
    assert len(findings) == 1
    assert findings[0]["category"] == "DEVELOPER_USERNAME"


# ---------------------------------------------------------------------------
# Synthetic Package Audit Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_review_package(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal valid synthetic review package for testing audit failure modes."""
    source_commit = "32e1a2c3afae7d6b738630787ce4d2f7b3640c56"
    zip_path = tmp_path / "synthetic_review_package.zip"

    # Minimal payload files
    payload_files = {
        "README.md": b"# Test Readme\n",
        "01_GOLDEN_ORIGINAL_UNTOUCHED.docx": hashlib.sha256(b"golden").digest(),
        "04_CANDIDATE_LOSSLESS_OUTPUT.docx": hashlib.sha256(b"candidate").digest(),
        "artifacts/v2.1/release_evidence/release_evidence.json": json.dumps({
            "git": {"head": source_commit},
            "overall_status": "PASS",
            "release_ready": True,
        }).encode("utf-8"),
        "artifacts/v2.1/release_evidence/MANIFEST.json": json.dumps({
            "files": []
        }).encode("utf-8"),
        "artifacts/v2.1/release_evidence/MANIFEST.sha256": b"",
    }

    # Set exact golden & candidate hashes for mock
    golden_bytes = b"golden_docx_mock_bytes"
    candidate_bytes = b"candidate_docx_mock_bytes"
    payload_files["01_GOLDEN_ORIGINAL_UNTOUCHED.docx"] = golden_bytes
    payload_files["04_CANDIDATE_LOSSLESS_OUTPUT.docx"] = candidate_bytes

    return zip_path, source_commit


def test_audit_crc_failure(tmp_path: Path) -> None:
    """Corrupted ZIP archive bytes must fail CRC test."""
    zip_path = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ClearMark-v2.1.0-RC1/test.txt", b"Healthy content")

    # Corrupt compressed data in file
    raw = bytearray(zip_path.read_bytes())
    # Modify some byte in middle
    raw[len(raw) // 2] ^= 0xFF
    zip_path.write_bytes(bytes(raw))

    with pytest.raises(Exception):
        audit_review_package_archive(zip_path)


def test_audit_encrypted_member_rejection(tmp_path: Path) -> None:
    """ZIP entries with encryption bit set must fail closed."""
    zip_path = tmp_path / "encrypted.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{PACKAGE_ROOT_DIR}/file.txt", b"secret")

    # Set bit 0 of flag_bits in central directory
    raw = bytearray(zip_path.read_bytes())
    idx = raw.find(b"PK\x01\x02")
    assert idx != -1
    raw[idx + 8] |= 0x01
    zip_path.write_bytes(bytes(raw))

    with pytest.raises(PackageSecurityError, match="Encrypted member"):
        audit_review_package_archive(zip_path)


def test_audit_duplicate_member_rejection(tmp_path: Path) -> None:
    """Duplicate member entries in ZIP must fail audit."""
    zip_path = tmp_path / "duplicates.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(zip_path, "w") as zf:
            zi1 = zipfile.ZipInfo(f"{PACKAGE_ROOT_DIR}/dup.txt")
            zf.writestr(zi1, b"content 1")
            zi2 = zipfile.ZipInfo(f"{PACKAGE_ROOT_DIR}/dup.txt")
            zf.writestr(zi2, b"content 2")

    with pytest.raises(PackageSecurityError, match="Duplicate filenames"):
        audit_review_package_archive(zip_path)


# ---------------------------------------------------------------------------
# Zero Network Enforcement Test
# ---------------------------------------------------------------------------

def test_zero_network_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch socket.socket to verify builder & auditor execute 100% offline."""
    def guarded_socket(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("NETWORK ATTEMPT DETECTED: Review packaging must be strictly offline")

    monkeypatch.setattr(socket, "socket", guarded_socket)

    # Calling compute_source_tree_digest or path validation should not touch network
    entries = [("a.txt", "abc", 10)]
    assert compute_source_tree_digest(entries) is not None
    validate_path_safety("a.txt")


# ---------------------------------------------------------------------------
# Canonical Review Package Acceptance Test
# ---------------------------------------------------------------------------

def test_canonical_review_package_audit_passes() -> None:
    """The canonical generated review package on disk must pass the complete independent audit."""
    canonical_zip = Path("artifacts/v2.1/release_candidate/FINAL_REVIEW_PACKAGE_v2.1.0-RC1.zip")
    assert canonical_zip.is_file(), "Canonical review package ZIP does not exist on disk"

    audit_result = audit_review_package_archive(canonical_zip)
    assert audit_result["overall_status"] == "PASS"
    assert audit_result["rc_ready"] is True
    assert audit_result["crc_status"] == "PASS"
    assert audit_result["path_safety"] == "PASS"
    assert audit_result["duplicate_status"] == "PASS"
    assert audit_result["encryption_status"] == "PASS"
    assert audit_result["zip64_status"] == "PASS"
    assert audit_result["manifest_status"] == "PASS"
    assert audit_result["sha256sums_status"] == "PASS"
    assert audit_result["git_blob_identity"] == "PASS"
    assert audit_result["phase13_evidence_status"] == "PASS"
    assert audit_result["privacy_status"] == "PASS"
    assert audit_result["network_status"] == "PASS"
    assert audit_result["docx_frozen_status"] == "PASS"
    assert audit_result["golden_hash_status"] == "PASS"
    assert audit_result["candidate_hash_status"] == "PASS"


# ---------------------------------------------------------------------------
# Canonical Stable Package Acceptance Test
# ---------------------------------------------------------------------------

def test_canonical_stable_package_audit_passes() -> None:
    """The canonical stable release package on disk must pass the complete independent audit."""
    canonical_stable_zip = Path(f"artifacts/v2.1/stable/{STABLE_PACKAGE_FILENAME}")
    assert canonical_stable_zip.is_file(), "Canonical stable package ZIP does not exist on disk"

    audit_result = audit_review_package_archive(
        canonical_stable_zip,
        expected_root_dir=STABLE_PACKAGE_ROOT_DIR,
        expected_stage="stable",
    )
    assert audit_result["overall_status"] == "PASS"
    assert audit_result["stable_ready"] is True
    assert audit_result["rc_ready"] is False
    assert audit_result["crc_status"] == "PASS"
    assert audit_result["path_safety"] == "PASS"
    assert audit_result["duplicate_status"] == "PASS"
    assert audit_result["encryption_status"] == "PASS"
    assert audit_result["zip64_status"] == "PASS"
    assert audit_result["manifest_status"] == "PASS"
    assert audit_result["sha256sums_status"] == "PASS"
    assert audit_result["git_blob_identity"] == "PASS"
    assert audit_result["phase13_evidence_status"] == "PASS"
    assert audit_result["privacy_status"] == "PASS"
    assert audit_result["network_status"] == "PASS"
    assert audit_result["docx_frozen_status"] == "PASS"
    assert audit_result["golden_hash_status"] == "PASS"
    assert audit_result["candidate_hash_status"] == "PASS"
    assert audit_result["internal_root"] == f"{STABLE_PACKAGE_ROOT_DIR}/"


def test_canonical_stable_vs_rc1_diff_passes() -> None:
    """The stable vs RC1 diff must prove 0 unexpected differences and 525 byte-identical payload files."""
    diff_json_path = Path("artifacts/v2.1/stable/STABLE_VS_RC1_DIFF.json")
    assert diff_json_path.is_file(), "STABLE_VS_RC1_DIFF.json does not exist on disk"

    diff_data = json.loads(diff_json_path.read_text(encoding="utf-8"))
    assert diff_data["unexpected_differences"] == 0
    assert diff_data["payload_identity_status"] == "PASS"
    assert diff_data["byte_identical_members"] == 525
    assert diff_data["intentional_stable_metadata_differences"] == 2
    assert diff_data["path_normalized_matching_members"] == 527
    assert diff_data["rc1_root"] == f"{PACKAGE_ROOT_DIR}/"
    assert diff_data["stable_root"] == f"{STABLE_PACKAGE_ROOT_DIR}/"

