"""tests/test_malformed_archives.py

Comprehensive test suite for Phase 9 Malformed File Hardening & Security Preflight.
Validates all 38 threat items, security limits, XML safety, zero-network XXE,
pipeline integration, CLI exit codes, HTTP statuses, and format adapter boundary isolation.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import struct
import sys
import urllib.request
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "service" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cli import ExitCode, main as cli_main
from pipeline import Pipeline
from pipeline_types import ErrorCode, PipelineStatus, ProcessingMode
from security import (
    SecurityFinding,
    SecurityLimits,
    SecurityPreflightResult,
    SecurityViolation,
    preflight_xml_data,
    preflight_zip_container,
    require_safe_zip_container,
    sanitize_report_string,
)
from tests.fixtures.security.build_hostile_fixtures import (
    FIXTURES_DIR,
    build_raw_zip,
    make_minimal_docx,
)


# ==============================================================================
# 1. UNIT TESTS: ZIP PATH SAFETY & ZIPSLIP (Threats 01-06, 08)
# ==============================================================================

class TestZipPathSafety:
    """Validate strict rejection of unsafe archive member path names."""

    def test_safe_path_acceptance(self):
        data = build_raw_zip([{"name": "word/document.xml", "data": b"<root/>"}])
        res = preflight_zip_container(data)
        assert res.is_safe
        assert res.total_members == 1

    def test_zipslip_parent_traversal_rejected(self):
        data = build_raw_zip([{"name": "../evil.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_PARENT"
        assert not exc_info.value.is_limit

    def test_zipslip_nested_parent_traversal_rejected(self):
        data = build_raw_zip([{"name": "folder/../../outside.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_PARENT"

    def test_zipslip_absolute_unix_path_rejected(self):
        data = build_raw_zip([{"name": "/etc/passwd", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_ABSOLUTE"

    def test_zipslip_windows_drive_letter_rejected(self):
        for drive in ("C:/evil.xml", "d:/evil.xml", "Z:/target"):
            data = build_raw_zip([{"name": drive, "data": b"<root/>"}])
            with pytest.raises(SecurityViolation) as exc_info:
                preflight_zip_container(data)
            assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_WINDOWS_DRIVE"

    def test_zipslip_backslash_rejected(self):
        data = build_raw_zip([{"name": "folder\\..\\evil.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_BACKSLASH"

    def test_zipslip_unc_path_rejected(self):
        data = build_raw_zip([{"name": "//server/share/evil.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_UNC"

    def test_zipslip_unc_backslash_path_rejected(self):
        data = build_raw_zip([{"name": "\\\\server\\share\\evil.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_UNC"

    def test_zipslip_nul_byte_injection_rejected(self):
        data = build_raw_zip([{"name": "test.xml\x00.txt", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_NUL_BYTE"

    def test_noncanonical_path_double_slash_rejected(self):
        data = build_raw_zip([{"name": "word//document.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_NONCANONICAL_PATH"

    def test_noncanonical_path_current_dir_rejected(self):
        data = build_raw_zip([{"name": "word/./document.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_NONCANONICAL_PATH"


# ==============================================================================
# 2. UNIT TESTS: ARCHIVE INTEGRITY & MEMBERS (Threats 07, 09, 10, 11)
# ==============================================================================

class TestArchiveIntegrity:
    """Validate duplicate members, symlinks, encryption, and compression methods."""

    def test_duplicate_members_rejected(self):
        data = build_raw_zip([
            {"name": "ppt/slides/slide1.xml", "data": b"<s1/>"},
            {"name": "ppt/slides/slide1.xml", "data": b"<s2/>"},
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_DUPLICATE_MEMBER"
        assert not exc_info.value.is_limit

    def test_symlink_member_rejected(self):
        symlink_attr = (0o120000 | 0o777) << 16  # S_IFLNK
        data = build_raw_zip([{"name": "symlink", "data": b"/etc/passwd", "external_attr": symlink_attr}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_SYMLINK_MEMBER"

    def test_encrypted_member_rejected(self):
        data = build_raw_zip([{"name": "secret.txt", "data": b"encrypted", "flags": 0x0001}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ENCRYPTED_MEMBER"

    def test_unsupported_compression_method_rejected(self):
        # Allowlist is STORED (0) and DEFLATED (8). Method 9 (Deflate64) or 12 must fail.
        for method in (9, 12, 14, 98):
            data = build_raw_zip([{"name": "file.txt", "data": b"hello", "comp_method": method}])
            with pytest.raises(SecurityViolation) as exc_info:
                preflight_zip_container(data)
            assert exc_info.value.finding.rule_id == "SEC_UNSUPPORTED_COMPRESSION"

    def test_stored_compression_method_accepted(self):
        data = build_raw_zip([{"name": "file.txt", "data": b"hello", "comp_method": 0}])
        res = preflight_zip_container(data)
        assert res.is_safe

    def test_forged_metadata_decompression_discrepancy_rejected(self):
        # Stored method where declared size != actual payload length
        data_stored = build_raw_zip([{"name": "stored.txt", "data": b"A" * 100, "comp_method": 0, "usize_override": 50}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data_stored)
        assert exc_info.value.finding.rule_id == "SEC_TRUNCATED_STREAM"

        # Deflated method where declared usize != actual decompressed bytes
        data_deflated = build_raw_zip([{"name": "deflated.txt", "data": b"A" * 200, "comp_method": 8, "usize_override": 50}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data_deflated)
        assert exc_info.value.finding.rule_id in ("SEC_TRUNCATED_STREAM", "SEC_CORRUPTED_STREAM")


# ==============================================================================
# 3. UNIT TESTS: RESOURCE LIMITS & BOUNDARY TESTS (Threats 12-15)
# ==============================================================================

class TestResourceLimits:
    """Validate numerical boundary conditions (below, at, above limit) for all limits."""

    def test_member_count_boundary(self):
        limits = SecurityLimits(max_member_count=3)
        # Below limit (2)
        d2 = build_raw_zip([{"name": f"f{i}.txt", "data": b"x"} for i in range(2)])
        assert preflight_zip_container(d2, limits=limits).is_safe

        # At limit (3)
        d3 = build_raw_zip([{"name": f"f{i}.txt", "data": b"x"} for i in range(3)])
        assert preflight_zip_container(d3, limits=limits).is_safe

        # Above limit (4)
        d4 = build_raw_zip([{"name": f"f{i}.txt", "data": b"x"} for i in range(4)])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d4, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_MEMBER_COUNT_LIMIT"
        assert exc_info.value.is_limit

    def test_member_uncompressed_bytes_boundary(self):
        limits = SecurityLimits(max_member_uncompressed_bytes=100)
        # At limit (100 B)
        d_at = build_raw_zip([{"name": "m.txt", "data": b"A" * 100, "comp_method": 0}])
        assert preflight_zip_container(d_at, limits=limits).is_safe

        # Above limit (101 B)
        d_above = build_raw_zip([{"name": "m.txt", "data": b"A" * 101, "comp_method": 0}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_MEMBER_UNCOMPRESSED_LIMIT"
        assert exc_info.value.is_limit

    def test_total_uncompressed_bytes_boundary(self):
        limits = SecurityLimits(max_total_uncompressed_bytes=200, max_member_uncompressed_bytes=150)
        # At limit (200 B total across 2 members)
        d_at = build_raw_zip([
            {"name": "m1.txt", "data": b"A" * 100, "comp_method": 0},
            {"name": "m2.txt", "data": b"B" * 100, "comp_method": 0},
        ])
        assert preflight_zip_container(d_at, limits=limits).is_safe

        # Above limit (201 B total)
        d_above = build_raw_zip([
            {"name": "m1.txt", "data": b"A" * 100, "comp_method": 0},
            {"name": "m2.txt", "data": b"B" * 101, "comp_method": 0},
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_TOTAL_UNCOMPRESSED_LIMIT"
        assert exc_info.value.is_limit

    def test_compression_ratio_limit(self):
        # Create highly repetitive payload (100 KiB of zeros compresses to ~100 B -> ratio ~1000)
        limits = SecurityLimits(max_compression_ratio=20.0)
        data = build_raw_zip([{"name": "bomb.txt", "data": b"\x00" * (100 * 1024)}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_COMPRESSION_RATIO_LIMIT"
        assert exc_info.value.is_limit

    def test_member_name_bytes_boundary(self):
        limits = SecurityLimits(max_member_name_bytes=20)
        # At limit (20 B)
        d_at = build_raw_zip([{"name": "a" * 20, "data": b"x"}])
        assert preflight_zip_container(d_at, limits=limits).is_safe

        # Above limit (21 B)
        d_above = build_raw_zip([{"name": "a" * 21, "data": b"x"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_MEMBER_NAME_LIMIT"
        assert exc_info.value.is_limit


# ==============================================================================
# 4. UNIT TESTS: BINARY STRUCTURAL HARDENING (Threats 17-24)
# ==============================================================================

class TestBinaryStructuralHardening:
    """Validate EOCD bounds, central directory, local headers, mismatch, overlap, and ZIP64."""

    def test_missing_eocd_rejected(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello"}])[:-22]
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_MISSING_EOCD"

    def test_truncated_eocd_rejected(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello"}])[:-10]
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id in ("SEC_TRUNCATED_EOCD", "SEC_MISSING_EOCD")

    def test_bad_cd_offset_rejected(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], cd_offset_override=999999)
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_BAD_CD_OFFSET"

    def test_truncated_central_directory_rejected(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], cd_size_override=999999)
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_TRUNCATED_CD"

    def test_bad_local_header_offset_rejected(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello", "lhoff_override": 999999}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_BAD_LOCAL_HEADER_OFFSET"

    def test_local_vs_central_filename_mismatch_rejected(self):
        data = build_raw_zip([{"name": "evil.xml", "local_name_bytes": b"good.xml", "data": b"<data/>"}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_LOCAL_CENTRAL_MISMATCH"

    def test_overlapping_member_ranges_rejected(self):
        data = build_raw_zip([
            {"name": "member1.txt", "data": b"A" * 10, "csize_override": 100, "comp_method": 0},
            {"name": "member2.txt", "data": b"B" * 10, "comp_method": 0},
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_OVERLAPPING_MEMBERS"

    def test_multidisk_archive_rejected(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], disk_num=1)
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_MULTIDISK_ARCHIVE"

    def test_zip64_unsupported_fail_closed(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], zip64_locator=True)
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIP64_UNSUPPORTED"

    def test_zip64_extra_field_in_cd_rejected(self):
        cd_extra = struct.pack("<HH", 0x0001, 8) + b"\x00" * 8
        data = build_raw_zip([{"name": "test.txt", "data": b"hello", "cd_extra_bytes": cd_extra}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIP64_UNSUPPORTED"

    def test_zip64_extra_field_in_local_header_rejected(self):
        loc_extra = struct.pack("<HH", 0x0001, 8) + b"\x00" * 8
        data = build_raw_zip([{"name": "test.txt", "data": b"hello", "loc_extra_bytes": loc_extra}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_ZIPSLIP_PARENT" or exc_info.value.finding.rule_id == "SEC_ZIP64_UNSUPPORTED"
        assert exc_info.value.finding.rule_id == "SEC_ZIP64_UNSUPPORTED"

    def test_payload_overlaps_next_local_header_rejected(self):
        # Member 1 compressed payload extends across member 2's local header offset
        data = build_raw_zip([
            {"name": "m1.txt", "data": b"A" * 10, "csize_override": 80, "comp_method": 0},
            {"name": "m2.txt", "data": b"B" * 20, "comp_method": 0},
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_OVERLAPPING_MEMBERS"

    def test_data_descriptor_bit3_safely_supported(self):
        # Bit 3 set: sizes in local header set to 0, data descriptor with signature placed after payload
        uncomp = b"Safe data descriptor payload"
        crc = zlib.crc32(uncomp) & 0xFFFFFFFF
        desc = struct.pack("<IIII", 0x08074B50, crc, len(uncomp), len(uncomp))
        data = build_raw_zip([
            {
                "name": "desc.txt",
                "data": uncomp,
                "comp_method": 0,
                "flags": 0x0008,
                "desc_bytes": desc,
            }
        ])
        res = preflight_zip_container(data)
        assert res.is_safe
        assert res.total_members == 1

    def test_eocd_trailing_bytes_rejected(self):
        data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], trailing_bytes=b"UNAUTHORIZED_TRAILING_OVERLAY")
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id in ("SEC_TRUNCATED_EOCD", "SEC_MISSING_EOCD")


# ==============================================================================
# 4B. UNIT TESTS: DATA DESCRIPTORS & PHYSICAL RANGE VALIDATION
# ==============================================================================

class TestZipDataDescriptorsAndPhysicalRange:
    """Validate signed (16-byte) and unsigned (12-byte) data descriptors, field validation,
    local/central flag consistency, descriptor-aware physical range bounds, and fake signature resistance.
    """

    def test_signed_data_descriptor_valid_accepted(self):
        uncomp = b"Valid signed descriptor payload"
        data = build_raw_zip([
            {"name": "s.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": True}
        ])
        res = preflight_zip_container(data)
        assert res.is_safe
        assert res.total_members == 1

    def test_signed_data_descriptor_crc_mismatch_rejected(self):
        uncomp = b"Signed descriptor payload"
        data = build_raw_zip([
            {"name": "s.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": True, "desc_crc": 0xDEADBEEF}
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_DATA_DESCRIPTOR_MISMATCH"

    def test_signed_data_descriptor_compressed_size_mismatch_rejected(self):
        uncomp = b"Signed descriptor payload"
        data = build_raw_zip([
            {"name": "s.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": True, "desc_csize": 9999}
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_DATA_DESCRIPTOR_MISMATCH"

    def test_signed_data_descriptor_uncompressed_size_mismatch_rejected(self):
        uncomp = b"Signed descriptor payload"
        data = build_raw_zip([
            {"name": "s.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": True, "desc_usize": 9999}
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_DATA_DESCRIPTOR_MISMATCH"

    def test_signed_data_descriptor_overlapping_next_member_rejected(self):
        # Member 1 has signed descriptor (16 B). Member 2 starts inside Member 1's descriptor span.
        m1_payload = b"A" * 20
        # 16-byte signed descriptor with CRC=0x04034B50 (which matches member 2 local signature)
        m1_desc = struct.pack("<IIII", 0x08074B50, 0x04034B50, 20, 0)
        m2_rest = struct.pack("<HIIIHH", 0, 0, 0, 0, 6, 0) + b"m2.txt"

        raw_body = (
            struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0008, 0, 0, 0, 0, 0, 0, 6, 0)
            + b"m1.txt"
            + m1_payload
            + m1_desc
            + m2_rest
        )
        cd_pos = len(raw_body)
        cd1 = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x0008, 0, 0, 0, 0x04034B50, 20, 0, 6, 0, 0, 0, 0, 0, 0) + b"m1.txt"
        cd2 = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 0, 60) + b"m2.txt"
        cd = cd1 + cd2
        eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 2, 2, len(cd), cd_pos, 0)
        full_zip = raw_body + cd + eocd

        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(full_zip)
        assert exc_info.value.finding.rule_id == "SEC_OVERLAPPING_MEMBERS"

    def test_unsigned_data_descriptor_valid_accepted(self):
        uncomp = b"Valid unsigned descriptor payload"
        data = build_raw_zip([
            {"name": "u.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": False}
        ])
        res = preflight_zip_container(data)
        assert res.is_safe
        assert res.total_members == 1

    def test_unsigned_data_descriptor_crc_mismatch_rejected(self):
        uncomp = b"Unsigned descriptor payload"
        data = build_raw_zip([
            {"name": "u.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": False, "desc_crc": 0xCAFEBABE}
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_DATA_DESCRIPTOR_MISMATCH"

    def test_unsigned_data_descriptor_compressed_size_mismatch_rejected(self):
        uncomp = b"Unsigned descriptor payload"
        data = build_raw_zip([
            {"name": "u.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": False, "desc_csize": 8888}
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_DATA_DESCRIPTOR_MISMATCH"

    def test_unsigned_data_descriptor_uncompressed_size_mismatch_rejected(self):
        uncomp = b"Unsigned descriptor payload"
        data = build_raw_zip([
            {"name": "u.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "desc_signed": False, "desc_usize": 8888}
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_DATA_DESCRIPTOR_MISMATCH"

    def test_unsigned_data_descriptor_overlapping_next_member_rejected(self):
        # Member 1 has unsigned descriptor (12 B). Member 2 starts inside Member 1's descriptor span.
        m1_payload = b"A" * 20
        # 12-byte unsigned descriptor with CRC=0x04034B50
        m1_desc = struct.pack("<III", 0x04034B50, 20, 0)
        m2_rest = struct.pack("<HIIIHH", 0, 0, 0, 0, 6, 0) + b"m2.txt"

        raw_body = (
            struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0008, 0, 0, 0, 0, 0, 0, 6, 0)
            + b"m1.txt"
            + m1_payload
            + m1_desc
            + m2_rest
        )
        cd_pos = len(raw_body)
        cd1 = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x0008, 0, 0, 0, 0x04034B50, 20, 0, 6, 0, 0, 0, 0, 0, 0) + b"m1.txt"
        cd2 = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 0, 56) + b"m2.txt"
        cd = cd1 + cd2
        eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 2, 2, len(cd), cd_pos, 0)
        full_zip = raw_body + cd + eocd

        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(full_zip)
        assert exc_info.value.finding.rule_id == "SEC_OVERLAPPING_MEMBERS"

    def test_bit3_local_vs_central_flag_mismatch_rejected(self):
        # Local has bit 3, Central does not
        d1 = build_raw_zip([{"name": "m.txt", "data": b"test", "comp_method": 0, "loc_flags": 0x0008, "cd_flags": 0x0000}])
        with pytest.raises(SecurityViolation) as exc1:
            preflight_zip_container(d1)
        assert exc1.value.finding.rule_id == "SEC_LOCAL_CENTRAL_MISMATCH"

        # Central has bit 3, Local does not
        d2 = build_raw_zip([{"name": "m.txt", "data": b"test", "comp_method": 0, "loc_flags": 0x0000, "cd_flags": 0x0008}])
        with pytest.raises(SecurityViolation) as exc2:
            preflight_zip_container(d2)
        assert exc2.value.finding.rule_id == "SEC_LOCAL_CENTRAL_MISMATCH"

    def test_no_bit3_local_vs_central_size_mismatch_rejected(self):
        # Bit 3 not set: local sizes must match Central Directory
        d_bad_size = build_raw_zip([{"name": "m.txt", "data": b"test", "comp_method": 0, "loc_csize": 999}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(d_bad_size)
        assert exc.value.finding.rule_id == "SEC_LOCAL_CENTRAL_MISMATCH"

    def test_signed_descriptor_containing_fake_local_header_signature_handled_safely(self):
        # Member 1 contains a signed descriptor whose CRC field is 0x04034B50 ('PK\x03\x04').
        # Using a payload whose true CRC32 is 0x04034B50 ensures CRC validation succeeds
        # while bytes in the descriptor literally contain b"PK\x03\x04".
        # Member 2 is located at its natural non-overlapping offset AFTER the descriptor.
        # Ensure central-directory driven parsing is not fooled by the fake signature inside the descriptor.
        uncomp = b"Hello fake signature descriptor\x80V\xf1\xe7"
        assert zlib.crc32(uncomp) == 0x04034B50
        desc = struct.pack("<IIII", 0x08074B50, 0x04034B50, len(uncomp), len(uncomp))
        data = build_raw_zip([
            {"name": "m1.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "crc": 0x04034B50, "desc_bytes": desc},
            {"name": "m2.txt", "data": b"m2 content", "comp_method": 0},
        ])
        res = preflight_zip_container(data)
        assert res.is_safe
        assert res.total_members == 2

    def test_unsigned_descriptor_containing_fake_local_header_signature_handled_safely(self):
        # Member 1 contains an unsigned 12-byte descriptor whose first 4 bytes (CRC) are 0x04034B50 ('PK\x03\x04').
        # A naive signature scanner would see b"PK\x03\x04" immediately following payload bytes.
        # Central-directory driven parsing guarantees member boundaries are unambiguous.
        uncomp = b"Hello fake signature descriptor\x80V\xf1\xe7"
        assert zlib.crc32(uncomp) == 0x04034B50
        desc = struct.pack("<III", 0x04034B50, len(uncomp), len(uncomp))
        data = build_raw_zip([
            {"name": "m1.txt", "data": uncomp, "comp_method": 0, "flags": 0x0008, "crc": 0x04034B50, "desc_bytes": desc},
            {"name": "m2.txt", "data": b"m2 content", "comp_method": 0},
        ])
        res = preflight_zip_container(data)
        assert res.is_safe
        assert res.total_members == 2


# ==============================================================================
# 5. UNIT TESTS: XML SECURITY & ZERO NETWORK (Threats 25-31)
# ==============================================================================

class TestXmlSecurity:
    """Validate XML size, depth, element count, DOCTYPE/ENTITY, and zero network calls."""

    def test_xml_part_size_boundary(self):
        limits = SecurityLimits(max_xml_part_bytes=50)
        # At limit
        xml_at = b"<root>" + b"x" * 36 + b"</root>"  # len 49 <= 50
        assert preflight_xml_data(xml_at, limits=limits).is_safe

        # Above limit
        xml_above = b"<root>" + b"x" * 45 + b"</root>"  # len 58 > 50
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_XML_PART_SIZE_LIMIT"
        assert exc_info.value.is_limit

    def test_xml_depth_boundary(self):
        limits = SecurityLimits(max_xml_depth=5)
        # Depth exactly 5
        xml_depth_5 = b"<a><b><c><d><e>leaf</e></d></c></b></a>"
        res = preflight_xml_data(xml_depth_5, limits=limits)
        assert res.is_safe
        assert res.max_xml_depth_observed == 5

        # Depth 6 (exceeds limit 5)
        xml_depth_6 = b"<a><b><c><d><e><f>leaf</f></e></d></c></b></a>"
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_depth_6, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_XML_DEPTH_LIMIT"
        assert exc_info.value.is_limit

    def test_xml_element_count_boundary(self):
        limits = SecurityLimits(max_xml_elements=4)
        # Exactly 4 elements: <root>, <e1/>, <e2/>, <e3/>
        xml_4 = b"<root><e1/><e2/><e3/></root>"
        res = preflight_xml_data(xml_4, limits=limits)
        assert res.is_safe
        assert res.total_xml_elements_observed == 4

        # 5 elements (exceeds limit 4)
        xml_5 = b"<root><e1/><e2/><e3/><e4/></root>"
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_5, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_XML_ELEMENT_COUNT_LIMIT"
        assert exc_info.value.is_limit

    def test_xml_doctype_rejected(self):
        xml = b'<?xml version="1.0"?>\n<!DOCTYPE html SYSTEM "http://127.0.0.1/test">\n<root/>'
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml, limits=SecurityLimits())
        assert exc_info.value.finding.rule_id == "SEC_XML_DOCTYPE"

    def test_xml_internal_entity_rejected(self):
        xml = b'<?xml version="1.0"?>\n<!DOCTYPE doc [<!ENTITY test "evil">]>\n<doc>&test;</doc>'
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml, limits=SecurityLimits())
        assert exc_info.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_ENTITY")

    def test_xml_utf16_doctype_bypass_prevention(self):
        text = '<?xml version="1.0" encoding="UTF-16"?>\n<!DOCTYPE doc [<!ENTITY test "evil">]>\n<doc/>'
        xml_bytes = text.encode("utf-16-le")
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_bytes, limits=SecurityLimits())
        assert exc_info.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_ENTITY")

    def test_xml_utf16_be_doctype_rejected(self):
        text = '<?xml version="1.0" encoding="UTF-16"?>\n<!DOCTYPE doc [<!ENTITY test "evil">]>\n<doc/>'
        xml_bytes = text.encode("utf-16-be")
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_bytes, limits=SecurityLimits())
        assert exc_info.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_ENTITY")

    def test_xml_utf8_bom_doctype_rejected(self):
        xml_bytes = b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE doc [<!ENTITY test "evil">]>\n<doc/>'
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_bytes, limits=SecurityLimits())
        assert exc_info.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_ENTITY")

    def test_xml_iso_8859_1_doctype_rejected(self):
        xml_bytes = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<!DOCTYPE doc [<!ENTITY test "evil">]>\n<doc/>'
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_bytes, limits=SecurityLimits())
        assert exc_info.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_ENTITY")

    def test_xml_zero_network_on_xxe(self, monkeypatch):
        """Prove that external entity references are rejected without attempting ANY network socket connection."""
        network_attempts = 0

        def forbidden_socket(*args, **kwargs):
            nonlocal network_attempts
            network_attempts += 1
            raise AssertionError("Security breach: network connection attempted during XML parsing!")

        monkeypatch.setattr(socket, "socket", forbidden_socket)
        monkeypatch.setattr(urllib.request, "urlopen", forbidden_socket)

        xxe_xml = (
            b'<?xml version="1.0"?>\n'
            b'<!DOCTYPE root SYSTEM "http://127.0.0.1:54321/external_xxe.dtd">\n'
            b'<root><data>&xxe;</data></root>'
        )
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xxe_xml, limits=SecurityLimits())

        assert exc_info.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_XXE_SYSTEM")
        assert network_attempts == 0, f"Expected 0 network attempts, observed {network_attempts}"

    def test_malformed_xml_fail_closed(self):
        unclosed = b"<w:document><w:body><w:p><w:t>unclosed"
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(unclosed, limits=SecurityLimits())
        assert exc_info.value.finding.rule_id == "SEC_XML_MALFORMED"


# ==============================================================================
# 6. INTEGRATION TESTS: CANONICAL PIPELINE FLOWS (Threats 32, 33, 34, 38)
# ==============================================================================

class TestPipelineSecurityIntegration:
    """Validate Pipeline.inspect, Pipeline.clean (dry_run and real), and adapter isolation."""

    @pytest.fixture
    def pipeline(self):
        return Pipeline()

    def test_inspect_hostile_zipslip_rejected(self, pipeline):
        hostile_file = FIXTURES_DIR / "zipslip_parent.zip"
        report = pipeline.inspect(hostile_file)
        assert report.status == PipelineStatus.ERROR
        assert report.error_code == ErrorCode.INVALID_CONTAINER
        assert "Security preflight failed" in report.error_message

    def test_inspect_hostile_xml_depth_rejected(self, pipeline):
        hostile_file = FIXTURES_DIR / "representative_deep_xml.pptx"
        report = pipeline.inspect(hostile_file)
        assert report.status == PipelineStatus.ERROR
        assert report.error_code == ErrorCode.PROCESSING_LIMIT_EXCEEDED
        assert "XML nesting depth" in report.error_message

    def test_dry_run_hostile_input_rejected(self, pipeline):
        """Dry-run is NOT an exemption from security validation."""
        hostile_file = FIXTURES_DIR / "representative_zipslip.docx"
        cleaned_bytes, report = pipeline.clean(hostile_file, dry_run=True)
        assert report.status == PipelineStatus.ERROR
        assert report.error_code == ErrorCode.INVALID_CONTAINER
        assert cleaned_bytes == b""

    def test_clean_real_hostile_input_emits_no_output(self, pipeline, tmp_path):
        out_path = tmp_path / "should_not_exist.docx"
        hostile_file = FIXTURES_DIR / "representative_zipslip.docx"
        cleaned_bytes, report = pipeline.clean(hostile_file, output_path=out_path)
        assert report.status == PipelineStatus.ERROR
        assert report.error_code == ErrorCode.INVALID_CONTAINER
        assert not out_path.exists(), "Hostile clean must not write any output file!"
        assert cleaned_bytes == b""

    def test_adapter_not_entered_on_hostile_docx(self, pipeline, monkeypatch):
        """Verify format-specific docx adapter is never invoked after security preflight fails."""
        adapter_spy = MagicMock()
        import docx
        monkeypatch.setattr(docx, "clean_docx_lossless", adapter_spy)

        hostile_file = FIXTURES_DIR / "representative_zipslip.docx"
        report = pipeline.inspect(hostile_file)
        assert report.status == PipelineStatus.ERROR
        assert adapter_spy.call_count == 0, "Docx adapter must never be entered on hostile input!"

    def test_adapter_not_entered_on_hostile_xlsx(self, pipeline, monkeypatch):
        adapter_spy = MagicMock()
        import xlsx
        monkeypatch.setattr(xlsx, "clean_xlsx_lossless", adapter_spy)

        hostile_file = FIXTURES_DIR / "representative_duplicate.xlsx"
        report = pipeline.inspect(hostile_file)
        assert report.status == PipelineStatus.ERROR
        assert adapter_spy.call_count == 0, "Xlsx adapter must never be entered on hostile input!"

    def test_adapter_not_entered_on_hostile_pptx(self, pipeline, monkeypatch):
        adapter_spy = MagicMock()
        import pptx
        monkeypatch.setattr(pptx, "clean_pptx_lossless", adapter_spy)

        hostile_file = FIXTURES_DIR / "representative_deep_xml.pptx"
        report = pipeline.inspect(hostile_file)
        assert report.status == PipelineStatus.ERROR
        assert adapter_spy.call_count == 0, "Pptx adapter must never be entered on hostile input!"


# ==============================================================================
# 7. INTEGRATION TESTS: TWO-FILE VERIFY CONTRACT (Threat 34)
# ==============================================================================

class TestVerifySecurityIntegration:
    """Validate two-file verify preflights both original and candidate before fidelity validation."""

    def test_verify_hostile_candidate_rejected_cli(self, monkeypatch, capsys):
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx")
        hostile_candidate = FIXTURES_DIR / "representative_zipslip.docx"

        test_args = ["watermarks", "verify", str(golden), str(hostile_candidate), "--json"]
        monkeypatch.setattr(sys, "argv", test_args)

        exit_code = cli_main()
        assert exit_code == ExitCode.INVALID_INPUT

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "INVALID_CONTAINER"
        assert data["rule_id"] == "SEC_ZIPSLIP_PARENT"
        assert "security preflight" in data["error_message"]

    def test_verify_hostile_original_rejected_cli(self, monkeypatch, capsys):
        hostile_orig = FIXTURES_DIR / "representative_zipslip.docx"
        candidate = Path("04_CANDIDATE_LOSSLESS_OUTPUT.docx")

        test_args = ["watermarks", "verify", str(hostile_orig), str(candidate), "--json"]
        monkeypatch.setattr(sys, "argv", test_args)

        exit_code = cli_main()
        assert exit_code == ExitCode.INVALID_INPUT

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "INVALID_CONTAINER"
        assert data["rule_id"] == "SEC_ZIPSLIP_PARENT"
        assert "security preflight" in data["error_message"]

    def test_verify_limit_original_rejected_cli(self, tmp_path, monkeypatch, capsys):
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx")
        overlimit_orig = tmp_path / "overlimit_orig.docx"
        overlimit_orig.write_bytes(FIXTURES_DIR / "representative_deep_xml.pptx").replace() if False else None
        # Build overlimit docx with deep XML
        deep_xml = b"<root>" + b"<node>" * 150 + b"leaf" + b"</node>" * 150 + b"</root>"
        overlimit_orig.write_bytes(make_minimal_docx({"word/document.xml": deep_xml}))

        test_args = ["watermarks", "verify", str(overlimit_orig), str(golden), "--json"]
        monkeypatch.setattr(sys, "argv", test_args)

        exit_code = cli_main()
        assert exit_code == ExitCode.LIMIT_EXCEEDED

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "PROCESSING_LIMIT_EXCEEDED"
        assert data["rule_id"] == "SEC_XML_DEPTH_LIMIT"

    def test_verify_limit_candidate_rejected_cli(self, tmp_path, monkeypatch, capsys):
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx")
        overlimit_cand = tmp_path / "overlimit_cand.docx"
        deep_xml = b"<root>" + b"<node>" * 150 + b"leaf" + b"</node>" * 150 + b"</root>"
        overlimit_cand.write_bytes(make_minimal_docx({"word/document.xml": deep_xml}))

        test_args = ["watermarks", "verify", str(golden), str(overlimit_cand), "--json"]
        monkeypatch.setattr(sys, "argv", test_args)

        exit_code = cli_main()
        assert exit_code == ExitCode.LIMIT_EXCEEDED

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "PROCESSING_LIMIT_EXCEEDED"
        assert data["rule_id"] == "SEC_XML_DEPTH_LIMIT"

    def test_verify_fidelity_invalid_safe_candidate_cli(self, tmp_path, monkeypatch, capsys):
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx")
        cand_path = tmp_path / "fidelity_invalid.docx"
        import zipfile
        with zipfile.ZipFile(golden, "r") as zin, zipfile.ZipFile(cand_path, "w") as zout:
            for item in zin.infolist():
                d = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    d = d.replace(b"</w:body>", b"<w:p><w:r><w:t>InjectedPara</w:t></w:r></w:p></w:body>")
                zout.writestr(item, d)

        test_args = ["watermarks", "verify", str(golden), str(cand_path), "--json"]
        monkeypatch.setattr(sys, "argv", test_args)

        exit_code = cli_main()
        assert exit_code == ExitCode.VALIDATION_FAILED

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["status"] == "FAIL"

    def test_verify_preflight_failure_skips_fidelity_validator(self, monkeypatch):
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx")
        hostile_candidate = FIXTURES_DIR / "representative_zipslip.docx"

        fidelity_spy = MagicMock()
        import tools.verify_document_fidelity
        monkeypatch.setattr(tools.verify_document_fidelity, "analyze_docx_fidelity", fidelity_spy)

        test_args = ["watermarks", "verify", str(golden), str(hostile_candidate), "--json"]
        monkeypatch.setattr(sys, "argv", test_args)

        exit_code = cli_main()
        assert exit_code == ExitCode.INVALID_INPUT
        assert fidelity_spy.call_count == 0, "Fidelity validator must NOT be invoked when preflight fails!"


# ==============================================================================
# 8. INTEGRATION TESTS: BATCH FAULT ISOLATION (Threat 35)
# ==============================================================================

class TestBatchFaultIsolation:
    """Validate that a hostile archive in a batch fails only that item; healthy siblings continue."""

    def test_batch_fault_isolation(self, tmp_path):
        from batch_processor import BatchProcessor

        # Prepare 3 files: 1 valid, 1 hostile, 1 valid
        f1 = tmp_path / "valid1.docx"
        shutil.copyfile("01_GOLDEN_ORIGINAL_UNTOUCHED.docx", f1)

        f2 = tmp_path / "hostile.docx"
        shutil.copyfile(FIXTURES_DIR / "representative_zipslip.docx", f2)

        f3 = tmp_path / "valid2.docx"
        shutil.copyfile("04_CANDIDATE_LOSSLESS_OUTPUT.docx", f3)

        processor = BatchProcessor()
        batch_report = processor.process_paths([f1, f2, f3], dry_run=True)

        assert len(batch_report.items) == 3
        # valid1 succeeded
        assert batch_report.items[0].status in ("INSPECTED", "NO_CHANGE_REQUIRED", "CLEANED")
        # hostile failed with ERROR
        assert batch_report.items[1].status == "ERROR"
        assert batch_report.items[1].error_code == "INVALID_CONTAINER"
        # valid2 succeeded despite sibling failure
        assert batch_report.items[2].status in ("INSPECTED", "NO_CHANGE_REQUIRED", "CLEANED")
        # Summary reconciles
        assert batch_report.summary.errors == 1
        assert batch_report.summary.reconcile() is True


# ==============================================================================
# 9. INTEGRATION TESTS: REPORT PRIVACY & LOG SANITIZATION (Threats 36, 37)
# ==============================================================================

class TestReportPrivacyAndSanitization:
    """Validate that security reports never leak document contents and sanitize strings."""

    def test_report_does_not_contain_document_body(self):
        doc_body = "TOP_SECRET_DOCUMENT_CONTENT_DO_NOT_LEAK"
        data = make_minimal_docx({
            "word/document.xml": f'<?xml version="1.0"?><!DOCTYPE html><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>{doc_body}</w:t></w:p></w:body></w:document>'.encode("utf-8")
        })
        pipeline = Pipeline()
        report = pipeline.inspect(data, filename="secret.docx")
        report_dict = report.to_dict()
        report_json = json.dumps(report_dict)

        assert report.status == PipelineStatus.ERROR
        assert doc_body not in report_json, "Document text must never leak in security reports!"

    def test_sanitize_report_string_strips_ansi_and_controls(self):
        # String with ANSI color codes and bell / backspace chars
        hostile_str = "\x1b[31mRedAlert\x1b[0m\x07\x08evil.xml"
        sanitized = sanitize_report_string(hostile_str)
        assert "\x1b" not in sanitized
        assert "[31m" not in sanitized
        assert "RedAlert" in sanitized
        assert "evil.xml" in sanitized

    def test_sanitize_report_string_truncates_excessive_length(self):
        long_str = "a" * 1000
        sanitized = sanitize_report_string(long_str, max_len=100)
        assert len(sanitized) <= 120
        assert sanitized.endswith("...[truncated]")


# ==============================================================================
# 10. COUNTEREXAMPLES: VALID CORPORA REMAIN ACCEPTED (Threat Regression)
# ==============================================================================

class TestValidCorporaAcceptance:
    """Verify that all legitimate DOCX, XLSX, PPTX fixtures pass security preflight without regression."""

    def test_golden_docx_accepted(self):
        data = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx").read_bytes()
        res = preflight_zip_container(data)
        assert res.is_safe

    def test_candidate_docx_accepted(self):
        data = Path("04_CANDIDATE_LOSSLESS_OUTPUT.docx").read_bytes()
        res = preflight_zip_container(data)
        assert res.is_safe

    def test_phase7_xlsx_baseline_accepted(self):
        p = Path("tests/fixtures/xlsx_lossless/synthetic_baseline.xlsx")
        if p.exists():
            res = preflight_zip_container(p.read_bytes())
            assert res.is_safe

    def test_phase8_pptx_baseline_accepted(self):
        p = Path("tests/fixtures/pptx_lossless/synthetic_baseline.pptx")
        if p.exists():
            res = preflight_zip_container(p.read_bytes())
            assert res.is_safe


# ==============================================================================
# 11. INTEGRATION TESTS: HTTP API ENDPOINTS
# ==============================================================================

@pytest.fixture(scope="module")
def server_conn():
    import server
    import http.client
    import threading
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    yield c
    c.close()
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _api_post(conn, path: str, payload: dict) -> tuple[int, dict]:
    conn.request(
        "POST",
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, json.loads(data) if data else {}


class TestHttpApiSecurityIntegration:
    """Validate HTTP API error mapping on hostile containers."""

    def test_http_inspect_hostile_rejected(self, server_conn):
        import base64
        hostile_file = FIXTURES_DIR / "representative_zipslip.docx"
        raw = hostile_file.read_bytes()
        status, body = _api_post(
            server_conn,
            "/inspect",
            {"file": base64.b64encode(raw).decode("ascii"), "name": "evil.docx"},
        )
        assert status == 400
        assert body["ok"] is False

    def test_http_clean_hostile_rejected(self, server_conn):
        import base64
        hostile_file = FIXTURES_DIR / "representative_zipslip.docx"
        raw = hostile_file.read_bytes()
        status, body = _api_post(
            server_conn,
            "/clean",
            {"file": base64.b64encode(raw).decode("ascii"), "name": "evil.docx"},
        )
        assert status == 400
        assert body["ok"] is False

    def test_http_verify_hostile_rejected(self, server_conn):
        import base64
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx").read_bytes()
        hostile = (FIXTURES_DIR / "representative_zipslip.docx").read_bytes()
        status, body = _api_post(
            server_conn,
            "/verify",
            {
                "original": base64.b64encode(golden).decode("ascii"),
                "candidate": base64.b64encode(hostile).decode("ascii"),
                "format": "docx",
            },
        )
        assert status == 400
        assert body["ok"] is False
        assert body["status"] == "ERROR"
        assert body["error_code"] == "INVALID_CONTAINER"
        assert body["rule_id"] == "SEC_ZIPSLIP_PARENT"
        assert "security preflight" in body["error_message"]

    def test_http_verify_limit_original_rejected(self, server_conn):
        import base64
        deep_xml = b"<root>" + b"<node>" * 150 + b"leaf" + b"</node>" * 150 + b"</root>"
        overlimit_orig = make_minimal_docx({"word/document.xml": deep_xml})
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx").read_bytes()
        status, body = _api_post(
            server_conn,
            "/verify",
            {
                "original": base64.b64encode(overlimit_orig).decode("ascii"),
                "candidate": base64.b64encode(golden).decode("ascii"),
                "format": "docx",
            },
        )
        assert status == 413
        assert body["ok"] is False
        assert body["status"] == "ERROR"
        assert body["error_code"] == "PROCESSING_LIMIT_EXCEEDED"
        assert body["rule_id"] == "SEC_XML_DEPTH_LIMIT"

    def test_http_verify_limit_candidate_rejected(self, server_conn):
        import base64
        deep_xml = b"<root>" + b"<node>" * 150 + b"leaf" + b"</node>" * 150 + b"</root>"
        overlimit_cand = make_minimal_docx({"word/document.xml": deep_xml})
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx").read_bytes()
        status, body = _api_post(
            server_conn,
            "/verify",
            {
                "original": base64.b64encode(golden).decode("ascii"),
                "candidate": base64.b64encode(overlimit_cand).decode("ascii"),
                "format": "docx",
            },
        )
        assert status == 413
        assert body["ok"] is False
        assert body["status"] == "ERROR"
        assert body["error_code"] == "PROCESSING_LIMIT_EXCEEDED"
        assert body["rule_id"] == "SEC_XML_DEPTH_LIMIT"

    def test_http_verify_fidelity_invalid_safe_candidate(self, server_conn):
        import base64
        import io, zipfile
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx").read_bytes()
        bio_in = io.BytesIO(golden)
        bio_out = io.BytesIO()
        with zipfile.ZipFile(bio_in, "r") as zin, zipfile.ZipFile(bio_out, "w") as zout:
            for item in zin.infolist():
                d = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    d = d.replace(b"</w:body>", b"<w:p><w:r><w:t>InjectedPara</w:t></w:r></w:p></w:body>")
                zout.writestr(item, d)
        cand_bytes = bio_out.getvalue()

        status, body = _api_post(
            server_conn,
            "/verify",
            {
                "original": base64.b64encode(golden).decode("ascii"),
                "candidate": base64.b64encode(cand_bytes).decode("ascii"),
                "format": "docx",
            },
        )
        assert status == 422
        assert body["ok"] is False
        assert body["status"] == "FAIL"


# ==============================================================================
# 12. BOUNDARY TESTS (Section 9: Below Limit, At Limit, Above Limit)
# ==============================================================================

class TestBoundaryConditions:
    """Validate numerical boundary conditions for all 7 numeric SecurityLimits:
    <= limit accepted, > limit rejected.
    """

    def test_member_count_exact_boundaries(self):
        limits = SecurityLimits(max_member_count=3)
        # Below: 2 members
        d_below = build_raw_zip([{"name": f"f{i}.txt", "data": b"x"} for i in range(2)])
        assert preflight_zip_container(d_below, limits=limits).is_safe

        # At: 3 members
        d_at = build_raw_zip([{"name": f"f{i}.txt", "data": b"x"} for i in range(3)])
        assert preflight_zip_container(d_at, limits=limits).is_safe

        # Above: 4 members
        d_above = build_raw_zip([{"name": f"f{i}.txt", "data": b"x"} for i in range(4)])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_MEMBER_COUNT_LIMIT"
        assert exc_info.value.is_limit

    def test_member_uncompressed_bytes_exact_boundaries(self):
        limits = SecurityLimits(max_member_uncompressed_bytes=100)
        # Below: 99 B
        d_below = build_raw_zip([{"name": "m.txt", "data": b"A" * 99, "comp_method": 0}])
        assert preflight_zip_container(d_below, limits=limits).is_safe

        # At: 100 B
        d_at = build_raw_zip([{"name": "m.txt", "data": b"A" * 100, "comp_method": 0}])
        assert preflight_zip_container(d_at, limits=limits).is_safe

        # Above: 101 B
        d_above = build_raw_zip([{"name": "m.txt", "data": b"A" * 101, "comp_method": 0}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_MEMBER_UNCOMPRESSED_LIMIT"
        assert exc_info.value.is_limit

    def test_total_uncompressed_bytes_exact_boundaries(self):
        limits = SecurityLimits(max_total_uncompressed_bytes=200, max_member_uncompressed_bytes=150)
        # Below: 199 B across 2 members
        d_below = build_raw_zip([
            {"name": "m1.txt", "data": b"A" * 100, "comp_method": 0},
            {"name": "m2.txt", "data": b"B" * 99, "comp_method": 0},
        ])
        assert preflight_zip_container(d_below, limits=limits).is_safe

        # At: 200 B across 2 members
        d_at = build_raw_zip([
            {"name": "m1.txt", "data": b"A" * 100, "comp_method": 0},
            {"name": "m2.txt", "data": b"B" * 100, "comp_method": 0},
        ])
        assert preflight_zip_container(d_at, limits=limits).is_safe

        # Above: 201 B across 2 members
        d_above = build_raw_zip([
            {"name": "m1.txt", "data": b"A" * 100, "comp_method": 0},
            {"name": "m2.txt", "data": b"B" * 101, "comp_method": 0},
        ])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_TOTAL_UNCOMPRESSED_LIMIT"
        assert exc_info.value.is_limit

    def test_compression_ratio_exact_boundaries(self):
        # Natural deflated member: usize=150, csize=15, ratio=10.0
        raw = (b"abcdefghij" * 15)[:150]
        d = build_raw_zip([{"name": "r.txt", "data": raw}])

        # At limit: max_compression_ratio=10.0, ratio=10.0 <= 10.0 -> accepted
        limits_at = SecurityLimits(max_compression_ratio=10.0, min_compressed_bytes_for_ratio=15)
        assert preflight_zip_container(d, limits=limits_at).is_safe

        # Above limit: max_compression_ratio=9.9, ratio=10.0 > 9.9 -> rejected
        limits_above = SecurityLimits(max_compression_ratio=9.9, min_compressed_bytes_for_ratio=15)
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d, limits=limits_above)
        assert exc_info.value.finding.rule_id == "SEC_COMPRESSION_RATIO_LIMIT"

    def test_xml_part_bytes_exact_boundaries(self):
        limits = SecurityLimits(max_xml_part_bytes=60)
        # Below: 59 B
        xml_below = b"<root>" + b"x" * 45 + b"</root>"  # len 58 <= 60
        assert preflight_xml_data(xml_below, limits=limits).is_safe

        # At: 60 B
        xml_at = b"<root>" + b"x" * 47 + b"</root>"  # len 60 <= 60
        assert preflight_xml_data(xml_at, limits=limits).is_safe

        # Above: 61 B
        xml_above = b"<root>" + b"x" * 48 + b"</root>"  # len 61 > 60
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_XML_PART_SIZE_LIMIT"
        assert exc_info.value.is_limit

    def test_xml_depth_exact_boundaries(self):
        limits = SecurityLimits(max_xml_depth=3)
        # Below: depth 2
        xml_below = b"<a><b>leaf</b></a>"
        assert preflight_xml_data(xml_below, limits=limits).max_xml_depth_observed == 2

        # At: depth 3
        xml_at = b"<a><b><c>leaf</c></b></a>"
        assert preflight_xml_data(xml_at, limits=limits).max_xml_depth_observed == 3

        # Above: depth 4
        xml_above = b"<a><b><c><d>leaf</d></c></b></a>"
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_XML_DEPTH_LIMIT"
        assert exc_info.value.is_limit

    def test_xml_element_count_exact_boundaries(self):
        limits = SecurityLimits(max_xml_elements=3)
        # Below: 2 elements (<root>, <e1/>)
        xml_below = b"<root><e1/></root>"
        assert preflight_xml_data(xml_below, limits=limits).total_xml_elements_observed == 2

        # At: 3 elements (<root>, <e1/>, <e2/>)
        xml_at = b"<root><e1/><e2/></root>"
        assert preflight_xml_data(xml_at, limits=limits).total_xml_elements_observed == 3

        # Above: 4 elements (<root>, <e1/>, <e2/>, <e3/>)
        xml_above = b"<root><e1/><e2/><e3/></root>"
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_xml_data(xml_above, limits=limits)
        assert exc_info.value.finding.rule_id == "SEC_XML_ELEMENT_COUNT_LIMIT"
        assert exc_info.value.is_limit


# ==============================================================================
# 13. COMPRESSION RATIO EDGE CASES (Section 10)
# ==============================================================================

class TestCompressionRatioEdgeCases:
    """Validate compression ratio calculation edge cases:
    - compressed_size = 0 (empty vs non-empty)
    - compressed_size below ratio floor threshold
    - compressed_size exactly ratio floor threshold
    - ratio exactly max
    - ratio just above max
    - zero division prevention
    """

    def test_compressed_size_zero_empty_file_accepted(self):
        # Empty member (0 bytes uncompressed, 0 bytes compressed): valid STORED
        data = build_raw_zip([{"name": "empty.txt", "data": b"", "comp_method": 0}])
        res = preflight_zip_container(data)
        assert res.is_safe

    def test_compressed_size_zero_with_positive_uncompressed_rejected(self):
        # Forged deflated entry declaring csize=0 with usize=1000: rejected immediately
        data = build_raw_zip([{"name": "forged.txt", "data": b"A" * 1000, "comp_method": 8, "csize_override": 0}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_COMPRESSION_RATIO_LIMIT"

    def test_compressed_size_below_ratio_floor_threshold(self):
        # Natural deflated member: usize=150, csize=15
        raw = (b"abcdefghij" * 15)[:150]
        d = build_raw_zip([{"name": "r.txt", "data": raw}])

        # min_compressed_bytes_for_ratio = 20 > csize (15)
        # effective_comp = 20 -> effective_ratio = 150 / 20 = 7.5
        limits_ok = SecurityLimits(max_compression_ratio=7.5, min_compressed_bytes_for_ratio=20)
        assert preflight_zip_container(d, limits=limits_ok).is_safe

        limits_bad = SecurityLimits(max_compression_ratio=7.4, min_compressed_bytes_for_ratio=20)
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d, limits=limits_bad)
        assert exc_info.value.finding.rule_id == "SEC_COMPRESSION_RATIO_LIMIT"

    def test_compressed_size_exactly_ratio_floor_threshold(self):
        # Natural deflated member: usize=150, csize=15
        raw = (b"abcdefghij" * 15)[:150]
        d = build_raw_zip([{"name": "r.txt", "data": raw}])

        # min_compressed_bytes_for_ratio = 15 == csize (15)
        # effective_comp = 15 -> ratio = 150 / 15 = 10.0
        limits_at = SecurityLimits(max_compression_ratio=10.0, min_compressed_bytes_for_ratio=15)
        assert preflight_zip_container(d, limits=limits_at).is_safe

        limits_above = SecurityLimits(max_compression_ratio=9.9, min_compressed_bytes_for_ratio=15)
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(d, limits=limits_above)
        assert exc_info.value.finding.rule_id == "SEC_COMPRESSION_RATIO_LIMIT"


# ==============================================================================
# 14. ENVIRONMENT OVERRIDES & SAFE FALLBACK (Section 7)
# ==============================================================================

class TestEnvironmentOverrides:
    """Validate that environment variable overrides work when valid and fall back safely when invalid."""

    def test_valid_environment_override(self, monkeypatch):
        monkeypatch.setenv("WATERMARKS_SECURITY_MAX_MEMBER_COUNT", "42")
        limits = SecurityLimits()
        assert limits.max_member_count == 42

    def test_malformed_environment_override_falls_back_safely(self, monkeypatch):
        # Non-numeric string falls back to authoritative default (10000)
        monkeypatch.setenv("WATERMARKS_SECURITY_MAX_MEMBER_COUNT", "not_a_number")
        limits = SecurityLimits()
        assert limits.max_member_count == 10000

    def test_negative_environment_override_falls_back_safely(self, monkeypatch):
        # Negative value falls back to authoritative default (10000)
        monkeypatch.setenv("WATERMARKS_SECURITY_MAX_MEMBER_COUNT", "-99")
        limits = SecurityLimits()
        assert limits.max_member_count == 10000

    def test_malformed_compression_ratio_falls_back_safely(self, monkeypatch):
        monkeypatch.setenv("WATERMARKS_SECURITY_MAX_COMPRESSION_RATIO", "invalid_ratio")
        limits = SecurityLimits()
        assert limits.max_compression_ratio == 100.0


# ==============================================================================
# 15. CANONICAL THREAT MATRIX TRACEABILITY (THREAT-01 through THREAT-38)
# ==============================================================================

class TestCanonicalThreatMatrixTraceability:
    """Unambiguous 1-to-1 executable test evidence for all 38 threats defined in
    docs/v2.1/PHASE9_SECURITY_THREAT_MATRIX.md.
    """

    def test_threat_01_zipslip_relative_traversal(self):
        data = build_raw_zip([{"name": "../traversal.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_ZIPSLIP_PARENT"

    def test_threat_02_zipslip_absolute_unix_path(self):
        data = build_raw_zip([{"name": "/etc/shadow", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_ZIPSLIP_ABSOLUTE"

    def test_threat_03_zipslip_windows_drive(self):
        data = build_raw_zip([{"name": "D:/system.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_ZIPSLIP_WINDOWS_DRIVE"

    def test_threat_04_zipslip_backslash(self):
        data = build_raw_zip([{"name": "path\\to\\file.xml", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_ZIPSLIP_BACKSLASH"

    def test_threat_05_zipslip_unc_path(self):
        for unc in ("//server/share/evil.xml", "\\\\server\\share\\evil.xml"):
            data = build_raw_zip([{"name": unc, "data": b"<root/>"}])
            with pytest.raises(SecurityViolation) as exc:
                preflight_zip_container(data)
            assert exc.value.finding.rule_id == "SEC_ZIPSLIP_UNC"

    def test_threat_06_zipslip_nul_byte(self):
        data = build_raw_zip([{"name": "doc.xml\x00.exe", "data": b"<root/>"}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_ZIPSLIP_NUL_BYTE"

    def test_threat_07_duplicate_members(self):
        data = build_raw_zip([{"name": "a.xml", "data": b"<a/>"}, {"name": "a.xml", "data": b"<b/>"}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_DUPLICATE_MEMBER"

    def test_threat_08_noncanonical_path_collisions(self):
        for bad_path in ("folder//file.xml", "folder/./file.xml"):
            data = build_raw_zip([{"name": bad_path, "data": b"<root/>"}])
            with pytest.raises(SecurityViolation) as exc:
                preflight_zip_container(data)
            assert exc.value.finding.rule_id == "SEC_NONCANONICAL_PATH"

    def test_threat_09_zip_symlink_entry(self):
        attr = (0o120000 | 0o777) << 16
        data = build_raw_zip([{"name": "link", "data": b"/etc/passwd", "external_attr": attr}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_SYMLINK_MEMBER"

    def test_threat_10_encrypted_member(self):
        data = build_raw_zip([{"name": "secret.xml", "data": b"enc", "flags": 0x0001}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_ENCRYPTED_MEMBER"

    def test_threat_11_unsupported_compression(self):
        data = build_raw_zip([{"name": "bad_comp.xml", "data": b"x", "comp_method": 9}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_UNSUPPORTED_COMPRESSION"

    def test_threat_12_archive_member_count_bomb(self):
        limits = SecurityLimits(max_member_count=5)
        data = build_raw_zip([{"name": f"f{i}.xml", "data": b"<x/>"} for i in range(6)])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data, limits=limits)
        assert exc.value.finding.rule_id == "SEC_MEMBER_COUNT_LIMIT"

    def test_threat_13_single_member_uncompressed_bomb(self):
        limits = SecurityLimits(max_member_uncompressed_bytes=1000)
        data = build_raw_zip([{"name": "bomb.txt", "data": b"A" * 1001, "comp_method": 0}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data, limits=limits)
        assert exc.value.finding.rule_id == "SEC_MEMBER_UNCOMPRESSED_LIMIT"

    def test_threat_14_total_uncompressed_bomb(self):
        limits = SecurityLimits(max_total_uncompressed_bytes=2000, max_member_uncompressed_bytes=1500)
        data = build_raw_zip([
            {"name": "b1.txt", "data": b"A" * 1200, "comp_method": 0},
            {"name": "b2.txt", "data": b"B" * 1200, "comp_method": 0},
        ])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data, limits=limits)
        assert exc.value.finding.rule_id == "SEC_TOTAL_UNCOMPRESSED_LIMIT"

    def test_threat_15_zipbomb_compression_ratio(self):
        limits = SecurityLimits(max_compression_ratio=25.0)
        data = build_raw_zip([{"name": "bomb.txt", "data": b"\x00" * (100 * 1024)}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data, limits=limits)
        assert exc.value.finding.rule_id == "SEC_COMPRESSION_RATIO_LIMIT"

    def test_threat_16_forged_metadata_decompression_discrepancy(self):
        data = build_raw_zip([{"name": "f.txt", "data": b"A" * 100, "comp_method": 0, "usize_override": 50}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_TRUNCATED_STREAM"

    def test_threat_17_crc32_and_corrupted_deflate(self):
        data_bad_crc = build_raw_zip([{"name": "f.xml", "data": b"<x/>", "crc": 0xdeadbeef}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data_bad_crc)
        assert exc.value.finding.rule_id == "SEC_CRC_MISMATCH"

        data_bad_stream = build_raw_zip([{"name": "f.xml", "data": b"<data>" + b"A" * 500 + b"</data>", "truncate_payload": True}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data_bad_stream)
        assert exc.value.finding.rule_id in ("SEC_TRUNCATED_STREAM", "SEC_CORRUPTED_STREAM")

    def test_threat_18_missing_and_truncated_eocd(self):
        data_no_eocd = build_raw_zip([{"name": "f.txt", "data": b"x"}])[:-25]
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data_no_eocd)
        assert exc.value.finding.rule_id == "SEC_MISSING_EOCD"

    def test_threat_19_central_directory_out_of_bounds(self):
        data_bad_cd = build_raw_zip([{"name": "f.txt", "data": b"x"}], cd_offset_override=999999)
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data_bad_cd)
        assert exc.value.finding.rule_id == "SEC_BAD_CD_OFFSET"

    def test_threat_20_local_file_header_out_of_bounds(self):
        data_bad_lhoff = build_raw_zip([{"name": "f.txt", "data": b"x", "lhoff_override": 999999}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data_bad_lhoff)
        assert exc.value.finding.rule_id == "SEC_BAD_LOCAL_HEADER_OFFSET"

    def test_threat_21_local_vs_central_mismatch(self):
        data = build_raw_zip([{"name": "cd_name.xml", "local_name_bytes": b"local_name.xml", "data": b"<x/>"}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_LOCAL_CENTRAL_MISMATCH"

    def test_threat_22_overlapping_archive_members(self):
        data = build_raw_zip([
            {"name": "m1.txt", "data": b"A" * 10, "csize_override": 80, "comp_method": 0},
            {"name": "m2.txt", "data": b"B" * 20, "comp_method": 0},
        ])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_OVERLAPPING_MEMBERS"

    def test_threat_23_multidisk_zip_unsupported(self):
        data = build_raw_zip([{"name": "f.txt", "data": b"x"}], disk_num=1)
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data)
        assert exc.value.finding.rule_id == "SEC_MULTIDISK_ARCHIVE"

    def test_threat_24_zip64_unsupported_fail_closed(self):
        data_loc = build_raw_zip([{"name": "f.txt", "data": b"x"}], zip64_locator=True)
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data_loc)
        assert exc.value.finding.rule_id == "SEC_ZIP64_UNSUPPORTED"

        cd_extra = struct.pack("<HH", 0x0001, 8) + b"\x00" * 8
        data_extra = build_raw_zip([{"name": "f.txt", "data": b"x", "cd_extra_bytes": cd_extra}])
        with pytest.raises(SecurityViolation) as exc:
            preflight_zip_container(data_extra)
        assert exc.value.finding.rule_id == "SEC_ZIP64_UNSUPPORTED"

    def test_threat_25_oversized_xml_part(self):
        limits = SecurityLimits(max_xml_part_bytes=40)
        xml_data = b"<root>" + b"x" * 35 + b"</root>"  # len 48 > 40
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(xml_data, limits=limits)
        assert exc.value.finding.rule_id == "SEC_XML_PART_SIZE_LIMIT"

    def test_threat_26_excessive_xml_depth(self):
        limits = SecurityLimits(max_xml_depth=4)
        xml_data = b"<a><b><c><d><e>deep</e></d></c></b></a>"
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(xml_data, limits=limits)
        assert exc.value.finding.rule_id == "SEC_XML_DEPTH_LIMIT"

    def test_threat_27_excessive_xml_element_count(self):
        limits = SecurityLimits(max_xml_elements=3)
        xml_data = b"<root><a/><b/><c/><d/></root>"
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(xml_data, limits=limits)
        assert exc.value.finding.rule_id == "SEC_XML_ELEMENT_COUNT_LIMIT"

    def test_threat_28_xml_doctype_and_entity(self):
        doctype_xml = b'<?xml version="1.0"?>\n<!DOCTYPE html SYSTEM "http://evil/x.dtd">\n<root/>'
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(doctype_xml, limits=SecurityLimits())
        assert exc.value.finding.rule_id == "SEC_XML_DOCTYPE"

        entity_xml = b'<?xml version="1.0"?>\n<!DOCTYPE doc [<!ENTITY e "x">]>\n<doc/>'
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(entity_xml, limits=SecurityLimits())
        assert exc.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_ENTITY")

    def test_threat_29_xxe_zero_network(self, monkeypatch):
        net_calls = 0
        def no_socket(*args, **kwargs):
            nonlocal net_calls
            net_calls += 1
            raise AssertionError("Network connection forbidden!")

        monkeypatch.setattr(socket, "socket", no_socket)
        xxe_payload = b'<?xml version="1.0"?>\n<!DOCTYPE r SYSTEM "http://127.0.0.1:9999/x.dtd"><r/>'
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(xxe_payload, limits=SecurityLimits())
        assert exc.value.finding.rule_id in ("SEC_XML_DOCTYPE", "SEC_XML_XXE_SYSTEM")
        assert net_calls == 0

    def test_threat_30_xml_encoding_bypass(self):
        # UTF-16 LE, UTF-16 BE, UTF-8 BOM, ISO-8859-1
        text = '<?xml version="1.0"?>\n<!DOCTYPE html><root/>'
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(text.encode("utf-16-le"), limits=SecurityLimits())
        assert exc.value.finding.rule_id == "SEC_XML_DOCTYPE"

        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(text.encode("utf-16-be"), limits=SecurityLimits())
        assert exc.value.finding.rule_id == "SEC_XML_DOCTYPE"

        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(b"\xef\xbb\xbf" + text.encode("utf-8"), limits=SecurityLimits())
        assert exc.value.finding.rule_id == "SEC_XML_DOCTYPE"

        iso_text = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<!DOCTYPE html><root/>'
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(iso_text.encode("iso-8859-1"), limits=SecurityLimits())
        assert exc.value.finding.rule_id == "SEC_XML_DOCTYPE"

    def test_threat_31_malformed_xml_syntax(self):
        bad_xml = b"<root><unclosed>text</root>"
        with pytest.raises(SecurityViolation) as exc:
            preflight_xml_data(bad_xml, limits=SecurityLimits())
        assert exc.value.finding.rule_id == "SEC_XML_MALFORMED"

    def test_threat_32_hostile_inspect(self):
        hostile_file = FIXTURES_DIR / "representative_zipslip.docx"
        rep = Pipeline().inspect(hostile_file)
        assert rep.status == PipelineStatus.ERROR
        assert rep.error_code == ErrorCode.INVALID_CONTAINER

    def test_threat_33_hostile_dry_run(self):
        hostile_file = FIXTURES_DIR / "representative_zipslip.docx"
        out_bytes, rep = Pipeline().clean(hostile_file, dry_run=True)
        assert rep.status == PipelineStatus.ERROR
        assert rep.error_code == ErrorCode.INVALID_CONTAINER
        assert out_bytes == b""

    def test_threat_34_hostile_verify(self, monkeypatch, capsys):
        golden = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx")
        hostile = FIXTURES_DIR / "representative_zipslip.docx"

        test_args = ["watermarks", "verify", str(golden), str(hostile), "--json"]
        monkeypatch.setattr(sys, "argv", test_args)
        exit_code = cli_main()
        assert exit_code == ExitCode.INVALID_INPUT

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "INVALID_CONTAINER"
        assert data["rule_id"] == "SEC_ZIPSLIP_PARENT"

    def test_threat_35_batch_isolation(self, tmp_path):
        from batch_processor import BatchProcessor
        f1 = tmp_path / "v1.docx"
        f2 = tmp_path / "hostile.docx"
        shutil.copyfile("01_GOLDEN_ORIGINAL_UNTOUCHED.docx", f1)
        shutil.copyfile(FIXTURES_DIR / "representative_zipslip.docx", f2)

        bp = BatchProcessor()
        rep = bp.process_paths([f1, f2], dry_run=True)
        assert len(rep.items) == 2
        assert rep.items[0].status in ("INSPECTED", "NO_CHANGE_REQUIRED", "CLEANED")
        assert rep.items[1].status == "ERROR"

    def test_threat_36_report_privacy(self):
        secret = "SECRET_USER_CONTENT_36"
        data = make_minimal_docx({
            "word/document.xml": f'<?xml version="1.0"?><!DOCTYPE doc><doc>{secret}</doc>'.encode("utf-8")
        })
        rep = Pipeline().inspect(data, filename="secret.docx")
        assert rep.status == PipelineStatus.ERROR
        assert secret not in json.dumps(rep.to_dict())

    def test_threat_37_log_json_escape_sanitization(self):
        dirty = "\x1b[31mBAD\x1b[0m\x00\x07name"
        cleaned = sanitize_report_string(dirty)
        assert "\x1b" not in cleaned
        assert "[31m" not in cleaned
        assert "\\x00" in cleaned or "\\x07" in cleaned

    def test_threat_38_adapter_not_entered(self, monkeypatch):
        spy = MagicMock()
        import docx
        monkeypatch.setattr(docx, "clean_docx_lossless", spy)
        Pipeline().inspect(FIXTURES_DIR / "representative_zipslip.docx")
        assert spy.call_count == 0

