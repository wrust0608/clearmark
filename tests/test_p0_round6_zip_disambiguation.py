"""tests/test_p0_round6_zip_disambiguation.py

P0 Round 6 Final Micro-Corrective Test Suite:
- Full EOCD candidate resolution with local header reference validation.
- Ambiguous EOCD candidate handling (multiple valid candidates fail closed as SEC_AMBIGUOUS_EOCD).
- Structural ZIP64 detection without global magic substring false positives (PK0606 / PK0607).
- Genuine immutability of ZipEocdInfo via frozen dataclass.
- SHA provenance and Git ancestry validation between evidence JSON and audit report.
"""

from __future__ import annotations

import io
import json
import re
import struct
import subprocess
import zipfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from service.scripts.security import (
    SecurityFinding,
    SecurityViolation,
    preflight_zip_container,
)
from service.scripts.zip_utils import (
    ZipEocdError,
    ZipEocdInfo,
    locate_zip_eocd,
)
from tests.fixtures.security.build_hostile_fixtures import build_raw_zip


def _build_test_zip(filename: str = "file.txt", content: bytes = b"content", comment: bytes = b"") -> bytes:
    """Helper to build a deterministic classic single-disk ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, content)
        if comment:
            zf.comment = comment
    return buf.getvalue()


# ==============================================================================
# 1. AMBIGUOUS EOCD & LOCAL REFERENCE VALIDATION WITNESSES
# ==============================================================================

def test_fake_cd_plus_fake_eocd_in_comment_not_silently_selected():
    """Verify that a ZIP with a copied CD record and fake EOCD in the comment fails closed as SEC_AMBIGUOUS_EOCD."""
    base_zip = _build_test_zip("doc.xml", b"<root>content</root>")
    real_info = locate_zip_eocd(base_zip)
    real_eocd_pos = real_info.offset
    real_cd_offset = real_info.cd_offset
    real_cd_size = real_info.cd_size
    cd_bytes = base_zip[real_cd_offset : real_cd_offset + real_cd_size]

    # Construct comment containing: prefix + cd_bytes + fake_eocd + suffix
    prefix = b"PREFIX_COMMENT_"
    real_eocd_without_comment = base_zip[: real_eocd_pos + 22]
    comment_start = len(real_eocd_without_comment)
    fake_cd_offset = comment_start + len(prefix)
    fake_cd_size = len(cd_bytes)
    fake_eocd_offset = fake_cd_offset + fake_cd_size
    suffix = b"_SUFFIX"
    fake_comment_len = len(suffix)

    fake_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0, 0, 1, 1,
        fake_cd_size,
        fake_cd_offset,
        fake_comment_len,
    )

    real_comment = prefix + cd_bytes + fake_eocd + suffix
    real_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0, 0, 1, 1,
        real_cd_size,
        real_cd_offset,
        len(real_comment),
    )

    craft_zip = base_zip[:real_eocd_pos] + real_eocd + real_comment

    # locate_zip_eocd must NOT silently choose fake or real; it must fail closed as SEC_AMBIGUOUS_EOCD
    with pytest.raises(ZipEocdError) as exc_info:
        locate_zip_eocd(craft_zip)
    assert exc_info.value.rule_id == "SEC_AMBIGUOUS_EOCD"
    assert "Multiple structurally valid EOCD interpretations exist" in str(exc_info.value)

    # Security preflight must also fail closed with SEC_AMBIGUOUS_EOCD
    with pytest.raises(SecurityViolation) as sec_exc:
        preflight_zip_container(craft_zip)
    assert sec_exc.value.finding.rule_id == "SEC_AMBIGUOUS_EOCD"


def test_fake_cd_with_corrupted_local_ref_ignored_for_real_eocd():
    """Verify that a fake CD in comment whose local reference is invalid is rejected, allowing real EOCD to be selected."""
    base_zip = _build_test_zip("doc.xml", b"<root>content</root>")
    real_info = locate_zip_eocd(base_zip)
    real_eocd_pos = real_info.offset
    real_cd_offset = real_info.cd_offset
    real_cd_size = real_info.cd_size
    cd_bytes = bytearray(base_zip[real_cd_offset : real_cd_offset + real_cd_size])

    # Corrupt local header offset in fake CD entry to point past archive boundary
    # Offset 42 is relative offset of local header
    cd_bytes[42:46] = struct.pack("<I", 0x7FFFFFFF)

    prefix = b"PREFIX_COMMENT_"
    real_eocd_without_comment = base_zip[: real_eocd_pos + 22]
    comment_start = len(real_eocd_without_comment)
    fake_cd_offset = comment_start + len(prefix)
    fake_cd_size = len(cd_bytes)
    fake_eocd_offset = fake_cd_offset + fake_cd_size
    suffix = b"_SUFFIX"
    fake_comment_len = len(suffix)

    fake_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0, 0, 1, 1,
        fake_cd_size,
        fake_cd_offset,
        fake_comment_len,
    )

    real_comment = prefix + bytes(cd_bytes) + fake_eocd + suffix
    real_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0, 0, 1, 1,
        real_cd_size,
        real_cd_offset,
        len(real_comment),
    )

    craft_zip = base_zip[:real_eocd_pos] + real_eocd + real_comment

    # Because fake CD entry is structurally invalid (bad local ref), only real EOCD is valid!
    info = locate_zip_eocd(craft_zip)
    assert info.offset == real_eocd_pos
    assert info.comment == real_comment


def test_candidate_local_header_signature_must_exist():
    """Verify candidate validation fails if referenced local header does not start with PK0304."""
    data = build_raw_zip([{"name": "test.txt", "data": b"hello"}])
    # Overwrite local header signature at offset 0 with garbage
    bad_data = bytearray(data)
    bad_data[0:4] = b"XXXX"

    with pytest.raises(SecurityViolation) as exc_info:
        preflight_zip_container(bytes(bad_data))
    assert exc_info.value.finding.rule_id == "SEC_INVALID_LOCAL_SIGNATURE"


def test_candidate_local_filename_must_match_cd_filename():
    """Verify candidate validation fails if local header filename differs from Central Directory."""
    data = build_raw_zip([{"name": "real.txt", "local_name_bytes": b"fake.txt", "data": b"hello"}])
    with pytest.raises(SecurityViolation) as exc_info:
        preflight_zip_container(data)
    assert exc_info.value.finding.rule_id == "SEC_LOCAL_CENTRAL_MISMATCH"


def test_candidate_local_header_offset_must_precede_cd():
    """Verify candidate validation fails if local_hdr_offset is not before CD offset."""
    data = build_raw_zip([{"name": "test.txt", "data": b"hello", "lhoff_override": 999999}])
    with pytest.raises(SecurityViolation) as exc_info:
        preflight_zip_container(data)
    assert exc_info.value.finding.rule_id == "SEC_BAD_LOCAL_HEADER_OFFSET"


def test_two_structurally_valid_eocds_fail_closed_as_ambiguous():
    """Verify that multiple valid EOCD interpretations trigger SEC_AMBIGUOUS_EOCD."""
    # Construct an archive with 2 valid EOCD records
    base_zip = _build_test_zip("data.bin", b"binary content")
    real_info = locate_zip_eocd(base_zip)
    cd_bytes = base_zip[real_info.cd_offset : real_info.cd_offset + real_info.cd_size]

    comment_start = real_info.offset + 22
    prefix = b"P"
    fake_cd_offset = comment_start + len(prefix)
    fake_cd_size = len(cd_bytes)
    fake_eocd_offset = fake_cd_offset + fake_cd_size
    suffix = b"S"

    fake_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0, 0, 1, 1,
        fake_cd_size,
        fake_cd_offset,
        len(suffix),
    )

    real_comment = prefix + cd_bytes + fake_eocd + suffix
    real_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0, 0, 1, 1,
        real_info.cd_size,
        real_info.cd_offset,
        len(real_comment),
    )

    ambiguous_zip = base_zip[:real_info.offset] + real_eocd + real_comment
    with pytest.raises(ZipEocdError) as exc_info:
        locate_zip_eocd(ambiguous_zip)
    assert exc_info.value.rule_id == "SEC_AMBIGUOUS_EOCD"


def test_bit3_local_header_deferred_sizes_still_supported():
    """Verify that bit-3/data-descriptor ZIPs with zeroed local header sizes remain supported."""
    # build_raw_zip with loc_flags=0x08 zeroing loc_crc, loc_csize, loc_usize
    data = build_raw_zip([
        {
            "name": "bit3_file.txt",
            "data": b"streaming compressed content with bit3 descriptor",
            "flags": 0x0008,
            "comp_method": 8,
        }
    ])
    info = locate_zip_eocd(data)
    assert info.total_entries == 1
    result = preflight_zip_container(data)
    assert result.is_safe


# ==============================================================================
# 2. STRUCTURAL ZIP64 DETECTION & FALSE POSITIVE WITNESSES
# ==============================================================================

def test_classic_zip_comment_pk0606_is_not_zip64():
    """Verify that b'PK\\x06\\x06' inside an archive comment does NOT trigger ZIP64 rejection."""
    data = _build_test_zip("test.txt", b"hello", comment=b"hello-PK\x06\x06-world")

    # Python zipfile must open it
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.read("test.txt") == b"hello"
        assert zf.comment == b"hello-PK\x06\x06-world"

    info = locate_zip_eocd(data)
    assert info.comment == b"hello-PK\x06\x06-world"

    result = preflight_zip_container(data)
    assert result.is_safe


def test_classic_zip_comment_pk0607_is_not_zip64():
    """Verify that b'PK\\x06\\x07' inside an archive comment does NOT trigger ZIP64 rejection."""
    data = _build_test_zip("test.txt", b"hello", comment=b"hello-PK\x06\x07-world")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.read("test.txt") == b"hello"
        assert zf.comment == b"hello-PK\x06\x07-world"

    info = locate_zip_eocd(data)
    assert info.comment == b"hello-PK\x06\x07-world"

    result = preflight_zip_container(data)
    assert result.is_safe


def test_classic_zip_payload_pk0606_is_not_zip64():
    """Verify that file payload containing b'PK\\x06\\x06' is accepted without ZIP64 false rejection."""
    payload = b"prefix-PK\x06\x06-binary-data"
    data = _build_test_zip("payload.bin", payload)

    info = locate_zip_eocd(data)
    assert info.total_entries == 1

    result = preflight_zip_container(data)
    assert result.is_safe


def test_classic_zip_payload_pk0607_is_not_zip64():
    """Verify that file payload containing b'PK\\x06\\x07' is accepted without ZIP64 false rejection."""
    payload = b"prefix-PK\x06\x07-binary-data"
    data = _build_test_zip("payload.bin", payload)

    info = locate_zip_eocd(data)
    assert info.total_entries == 1

    result = preflight_zip_container(data)
    assert result.is_safe


def test_real_zip64_still_fails_closed():
    """Verify that genuine ZIP64 containers with structural locators still fail closed."""
    data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], zip64_locator=True)
    with pytest.raises(SecurityViolation) as exc_info:
        preflight_zip_container(data)
    assert exc_info.value.finding.rule_id == "SEC_ZIP64_UNSUPPORTED"


# ==============================================================================
# 3. ZIP EOCD INFO IMMUTABILITY
# ==============================================================================

def test_zip_eocd_info_immutability():
    """Verify that ZipEocdInfo is genuinely frozen and attribute mutation is impossible."""
    info = ZipEocdInfo(
        offset=100,
        comment_length=0,
        comment=b"",
        disk_num=0,
        cd_disk=0,
        disk_entries=1,
        total_entries=1,
        cd_size=50,
        cd_offset=50,
    )

    # Verify tuple unpacking
    off, clen, c = info
    assert off == 100 and clen == 0 and c == b""
    assert info[0] == 100 and info[1] == 0 and info[2] == b""
    assert len(info) == 3
    assert info == (100, 0, b"")

    # Verify immutability
    with pytest.raises((FrozenInstanceError, AttributeError)):
        info.offset = 200  # type: ignore[misc]

    with pytest.raises((FrozenInstanceError, AttributeError)):
        info.comment = b"hacked"  # type: ignore[misc]


# ==============================================================================
# 4. EVIDENCE SHA PROVENANCE & SEMANTIC CONSISTENCY
# ==============================================================================

def test_evidence_sha_provenance_and_git_ancestry():
    """Verify evidence JSON and report maintain exact SHA provenance, commit ancestry, and issue invariants."""
    root_dir = Path(__file__).resolve().parent.parent
    evidence_path = root_dir / "docs" / "audits" / "V2_2_RC2_HARDENING_EVIDENCE.json"
    report_path = root_dir / "docs" / "audits" / "V2_2_RC2_HARDENING_REPORT.md"

    assert evidence_path.is_file(), f"Evidence file missing at {evidence_path}"
    assert report_path.is_file(), f"Report file missing at {report_path}"

    with open(evidence_path, "r", encoding="utf-8") as f:
        evidence = json.load(f)

    # Invariant: A19-A25 must NOT be in P0 evidence
    issues = evidence.get("issues", {})
    for reserved_id in [f"A{i:02d}" for i in range(19, 26)]:
        assert reserved_id not in issues, (
            f"Reserved issue identifier {reserved_id} must not exist in P0 evidence (reserved for P1)"
        )

    expected_p0_ids = [f"A{i:02d}" for i in range(1, 19)]
    assert sorted(issues.keys()) == expected_p0_ids, f"P0 issues must be exactly A01..A18, got {sorted(issues.keys())}"

    assert evidence.get("rc2_ready") is False, "rc2_ready must remain False"
    assert "P1_STATISTICAL_WATERMARK" in evidence.get("rc2_blocked_by", []), "P1 must be listed in rc2_blocked_by"

    # Verify report issue matrix table consistency
    report_text = report_path.read_text(encoding="utf-8")
    row_pattern = re.compile(r"\|\s*\*\*(A\d{2})\*\*\s*\|\s*(S[1-3])\s*\|\s*([^\|]+?)\s*\|")
    report_issues = {}
    for match in row_pattern.finditer(report_text):
        issue_id = match.group(1).replace("*", "").strip()
        sev = match.group(2).replace("*", "").strip()
        status = match.group(3).replace("*", "").strip()
        report_issues[issue_id] = {"severity": sev, "status": status}

    for issue_id in expected_p0_ids:
        assert issue_id in report_issues, f"Issue {issue_id} missing from report table"
        assert evidence["issues"][issue_id]["severity"] == report_issues[issue_id]["severity"]
        assert evidence["issues"][issue_id]["status"] == report_issues[issue_id]["status"]

    # Git SHA Provenance Verification
    round6_start_sha = evidence.get("round6_start_sha")
    code_end_sha = evidence.get("code_end_sha")
    report_source_sha = evidence.get("report_source_sha")

    assert round6_start_sha == "7191a75ac4b96d69e1228c93b46debb3b209c653", (
        f"round6_start_sha must be 7191a75ac4b96d69e1228c93b46debb3b209c653, got {round6_start_sha}"
    )
    assert code_end_sha is not None, "code_end_sha must be present in evidence JSON"
    assert report_source_sha == code_end_sha, "report_source_sha must equal code_end_sha"

    # Reject old Round4/Round5 SHAs
    stale_shas = {
        "466931f0bf082337a6a4e3230a10c9c3e2187bcf",
        "ff05cb68a3df7d55bdace8e38ddca7d1d1a85ed3",
        "e1b59ce12401f8274640fe5a5ae5d7fb7ffc0c45",
    }
    assert code_end_sha not in stale_shas, f"code_end_sha cannot be stale SHA {code_end_sha}"

    # Git Ancestry Checks
    def _run_git(args: list[str]) -> str:
        res = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=root_dir)
        if res.returncode != 0:
            raise AssertionError(f"git command failed: {' '.join(args)}\nError: {res.stderr}")
        return res.stdout.strip()

    # 1. Verify round6_start_sha is a valid commit
    _run_git(["rev-parse", "--verify", f"{round6_start_sha}^{{commit}}"])

    # 2. Verify code_end_sha is a valid commit
    _run_git(["rev-parse", "--verify", f"{code_end_sha}^{{commit}}"])

    # 3. Verify round6_start_sha is ancestor of code_end_sha
    res_start = subprocess.run(
        ["git", "merge-base", "--is-ancestor", round6_start_sha, code_end_sha],
        cwd=root_dir,
    )
    assert res_start.returncode == 0, f"{round6_start_sha} is not an ancestor of {code_end_sha}"

    # 4. Verify code_end_sha is ancestor of HEAD (or equal to HEAD)
    res_head = subprocess.run(
        ["git", "merge-base", "--is-ancestor", code_end_sha, "HEAD"],
        cwd=root_dir,
    )
    assert res_head.returncode == 0, f"{code_end_sha} is not an ancestor of HEAD"
