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

    def test_corrupted_crc32_rejected(self):
        data = build_raw_zip([{"name": "test.xml", "data": b"<test/>", "crc": 0x12345678}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id == "SEC_CRC_MISMATCH"

    def test_truncated_compressed_stream_rejected(self):
        data = build_raw_zip([{"name": "test.xml", "data": b"<data>" + b"Z" * 1000 + b"</data>", "truncate_payload": True}])
        with pytest.raises(SecurityViolation) as exc_info:
            preflight_zip_container(data)
        assert exc_info.value.finding.rule_id in ("SEC_TRUNCATED_STREAM", "SEC_CORRUPTED_STREAM")


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
        assert exit_code == ExitCode.VALIDATION_FAILED

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is False
        assert data["error_code"] == "INVALID_CONTAINER"
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
        assert data["error_code"] == "INVALID_CONTAINER"
        assert "security preflight" in data["error_message"]


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
        assert status == 422
        assert body["ok"] is False
        assert body["status"] == "FAIL"
        assert "security preflight" in body["error_message"]
