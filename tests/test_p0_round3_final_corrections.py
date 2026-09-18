"""Round 3 Final Corrective Verification Tests (P0 hardening).

Validates:
1. Performance gate restoration and assertion integrity (500 ms threshold preserved).
2. Portable sys.executable -m pytest evidence collection.
3. Byte-for-byte EOCD archive-level comment preservation in DOCX, XLSX, PPTX.
4. Fail-closed security on malformed EOCD comments.
5. Container extra-field policy preserving compatible unknown vendor fields and stripping incompatible Zip64/Growth hint.
6. Truthful P0 gate candidate and RC2 readiness status.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import zipfile

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "service/scripts"))

from service.scripts.docx.package import (
    DocxFidelityException,
    DocxPackage,
    _filter_rebuild_incompatible_extra_fields as docx_filter_extra,
)
from service.scripts.pptx.exceptions import PptxCorruptedPackageError
from service.scripts.pptx.package import (
    PptxPackage,
    _filter_rebuild_incompatible_extra_fields as pptx_filter_extra,
)
from service.scripts.xlsx.package import (
    XlsxFidelityException,
    XlsxPackage,
    _filter_rebuild_incompatible_extra_fields as xlsx_filter_extra,
)


# -----------------------------------------------------------------------------
# 1. Performance Gate Integrity
# -----------------------------------------------------------------------------


def test_performance_gate_remains_500ms():
    """Verify that the performance gate in test_performance_benchmarks.py is strictly 500 ms."""
    perf_test_file = REPO_ROOT / "tests/test_performance_benchmarks.py"
    assert perf_test_file.exists()
    content = perf_test_file.read_text(encoding="utf-8")

    # Gate must be 500 ms, not 1000 ms or any higher limit
    assert "assert elapsed_ms < 500" in content
    assert "assert elapsed_ms < 1000" not in content


def test_no_weakened_performance_assertion():
    """Verify no performance assertions were weakened, skipped, or xfailed in test_performance_benchmarks.py."""
    perf_test_file = REPO_ROOT / "tests/test_performance_benchmarks.py"
    content = perf_test_file.read_text(encoding="utf-8")

    assert "@pytest.mark.skip" not in content
    assert "@pytest.mark.xfail" not in content
    assert "assert elapsed_ms < 500" in content
    assert "assert peak_mem < 50 * 1024 * 1024" in content


# -----------------------------------------------------------------------------
# 2. Portable Evidence Collector
# -----------------------------------------------------------------------------


def test_evidence_collector_uses_python_m_pytest():
    """Verify test_evidence_test_ids_match_pytest_collection uses portable python -m pytest invocation."""
    round2_test_file = REPO_ROOT / "tests/test_p0_round2_review_corrections.py"
    assert round2_test_file.exists()
    content = round2_test_file.read_text(encoding="utf-8")

    # Static assertion: No Windows-specific pytest binary replacement
    assert 'replace("python.exe", "pytest.exe")' not in content
    assert "sys.executable" in content
    assert '"-m"' in content or "'-m'" in content
    assert '"pytest"' in content or "'pytest'" in content


# -----------------------------------------------------------------------------
# 3. EOCD Archive-Level Comment Preservation (DOCX, XLSX, PPTX)
# -----------------------------------------------------------------------------


def test_docx_preserves_eocd_archive_comment():
    """Verify DOCX package preserves original EOCD archive-level comment byte-for-byte upon rebuild."""
    test_comment = b"DocxProvenanceArchiveComment:V2_2_RC2_AUDIT_STAMP_98765"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("_rels/.rels", b"<Relationships/>")
        zf.writestr("word/document.xml", b"<w:document><w:body><w:p/></w:body></w:document>")
        zf.comment = test_comment

    raw_pkg = buf.getvalue()
    pkg = DocxPackage(raw_pkg)
    assert pkg._raw_eocd_comment == test_comment

    # Force a mutation to a target part to trigger native rebuild
    mutated_doc = b"<w:document><w:body><w:p><w:r><w:t>Mutated</w:t></w:r></w:p></w:body></w:document>"
    rebuilt = pkg.rebuild(changed_parts={"word/document.xml": mutated_doc})

    # Verify rebuilt ZIP has byte-identical archive comment
    zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt), "r")
    assert zf_rebuilt.comment == test_comment
    assert rebuilt.endswith(test_comment)


def test_xlsx_preserves_eocd_archive_comment():
    """Verify XLSX package preserves original EOCD archive-level comment byte-for-byte upon rebuild."""
    test_comment = b"XlsxProvenanceArchiveComment:SPREADSHEET_ORIGIN_VERIFIED_54321"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("_rels/.rels", b"<Relationships/>")
        zf.writestr("xl/workbook.xml", b"<workbook/>")
        zf.writestr("xl/sharedStrings.xml", b"<sst count='0'/>")
        zf.comment = test_comment

    raw_pkg = buf.getvalue()
    pkg = XlsxPackage(raw_pkg)
    assert pkg._raw_eocd_comment == test_comment

    mutated_sst = b"<sst count='1'><si><t>Cleaned</t></si></sst>"
    rebuilt = pkg.rebuild(changed_parts={"xl/sharedStrings.xml": mutated_sst})

    zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt), "r")
    assert zf_rebuilt.comment == test_comment
    assert rebuilt.endswith(test_comment)


def test_pptx_preserves_eocd_archive_comment():
    """Verify PPTX package preserves original EOCD archive-level comment byte-for-byte upon rebuild."""
    test_comment = b"PptxProvenanceArchiveComment:PRESENTATION_CLEARMARK_RC2_998877"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("_rels/.rels", b"<Relationships/>")
        zf.writestr("ppt/presentation.xml", b"<p:presentation/>")
        zf.writestr("ppt/slides/slide1.xml", b"<p:sld/>")
        zf.comment = test_comment

    raw_pkg = buf.getvalue()
    pkg = PptxPackage(raw_pkg)
    assert pkg._raw_eocd_comment == test_comment

    mutated_slide = b"<p:sld><p:cSld><p:spTree/></p:cSld></p:sld>"
    rebuilt = pkg.rebuild(changed_parts={"ppt/slides/slide1.xml": mutated_slide})

    zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt), "r")
    assert zf_rebuilt.comment == test_comment
    assert rebuilt.endswith(test_comment)


def test_empty_eocd_comment_roundtrip():
    """Verify that packages with no archive comment retain comment length = 0 upon rebuild."""
    for pkg_cls, main_part in [
        (DocxPackage, "word/document.xml"),
        (XlsxPackage, "xl/workbook.xml"),
        (PptxPackage, "ppt/presentation.xml"),
    ]:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", b"<Types/>")
            zf.writestr(main_part, b"<content/>")
            # Default comment is empty b""

        pkg = pkg_cls(buf.getvalue())
        assert pkg._raw_eocd_comment == b""

        rebuilt = pkg.rebuild(changed_parts={main_part: b"<mutated_content/>"})
        zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt), "r")
        assert zf_rebuilt.comment == b""

        eocd_idx = rebuilt.rfind(b"PK\x05\x06")
        comment_len = struct.unpack("<H", rebuilt[eocd_idx + 20 : eocd_idx + 22])[0]
        assert comment_len == 0


def test_malformed_eocd_comment_fails_closed():
    """Verify that malformed EOCD comment length exceeding package bounds fails closed."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr("word/document.xml", b"<doc/>")
        zf.writestr("xl/workbook.xml", b"<wb/>")
        zf.writestr("ppt/presentation.xml", b"<pres/>")

    raw = bytearray(buf.getvalue())
    idx = raw.rfind(b"PK\x05\x06")
    assert idx != -1

    # Overwrite comment_len to 5000, which exceeds buffer length
    struct.pack_into("<H", raw, idx + 20, 5000)
    bad_bytes = bytes(raw)

    with pytest.raises(DocxFidelityException, match="malformed EOCD comment length"):
        DocxPackage(bad_bytes)

    with pytest.raises(XlsxFidelityException, match="malformed EOCD comment length"):
        XlsxPackage(bad_bytes)

    with pytest.raises(PptxCorruptedPackageError, match="malformed EOCD comment length"):
        PptxPackage(bad_bytes)


# -----------------------------------------------------------------------------
# 4. Extra-Field Policy & Truthful Naming
# -----------------------------------------------------------------------------


def test_unknown_compatible_extra_field_preserved():
    """Verify that non-prohibited unknown vendor extra fields and timestamps are preserved."""
    ef_5455 = struct.pack("<HHBI", 0x5455, 5, 0x01, 1600000000)  # Extended timestamp
    ef_7875 = struct.pack("<HHBBBB", 0x7875, 4, 1, 1, 1, 1)      # Unix UID/GID
    ef_cafe = struct.pack("<HH", 0xCAFE, 8) + b"VENDORID"        # Unknown proprietary vendor extra field

    combined = ef_5455 + ef_7875 + ef_cafe

    for filter_fn, exc_cls in [
        (docx_filter_extra, DocxFidelityException),
        (xlsx_filter_extra, XlsxFidelityException),
        (pptx_filter_extra, PptxCorruptedPackageError),
    ]:
        filtered = filter_fn(combined, exc_cls)
        # All three compatible fields must be retained byte-for-byte
        assert filtered == combined


def test_zip64_extra_policy_remains_fail_closed():
    """Verify 0x0001 (Zip64) is stripped on rewrite and malformed extra fields fail closed."""
    ef_0001 = struct.pack("<HHQQ", 0x0001, 16, 999999, 999999)
    ef_ts = struct.pack("<HHBI", 0x5455, 5, 0x01, 1600000000)
    combined = ef_0001 + ef_ts

    for filter_fn, exc_cls in [
        (docx_filter_extra, DocxFidelityException),
        (xlsx_filter_extra, XlsxFidelityException),
        (pptx_filter_extra, PptxCorruptedPackageError),
    ]:
        filtered = filter_fn(combined, exc_cls)
        assert b"\x01\x00" not in filtered[:4]
        assert filtered == ef_ts

        # Malformed extra field with declared length larger than buffer
        malformed = struct.pack("<HH", 0x1234, 100) + b"short"
        with pytest.raises(exc_cls, match="truncated"):
            filter_fn(malformed, exc_cls)


def test_growth_hint_rebuild_policy():
    """Verify 0xA220 (Growth Hint) is stripped on rewritten parts while other fields are preserved."""
    ef_growth = struct.pack("<HHII", 0xA220, 8, 0, 1024)
    ef_vendor = struct.pack("<HH", 0xBEEF, 4) + b"DATA"
    combined = ef_growth + ef_vendor

    for filter_fn, exc_cls in [
        (docx_filter_extra, DocxFidelityException),
        (xlsx_filter_extra, XlsxFidelityException),
        (pptx_filter_extra, PptxCorruptedPackageError),
    ]:
        filtered = filter_fn(combined, exc_cls)
        assert filtered == ef_vendor


# -----------------------------------------------------------------------------
# 5. P0 Gate Candidate & RC2 Readiness Terminology
# -----------------------------------------------------------------------------


def test_p0_gate_does_not_claim_rc2_ready():
    """Verify audit report and evidence declare P0_GATE_CANDIDATE and do not prematurely claim RC2 readiness."""
    evidence_file = REPO_ROOT / "docs/audits/V2_2_RC2_HARDENING_EVIDENCE.json"
    assert evidence_file.exists()
    evidence_data = json.loads(evidence_file.read_text(encoding="utf-8"))

    # Evidence must explicitly state rc2_ready is False and list blocking phases
    assert evidence_data.get("rc2_ready") is False
    blocked_by = evidence_data.get("rc2_blocked_by", [])
    required_blocks = [
        "P1_STATISTICAL_WATERMARK",
        "P2_COMPONENT_MANAGER",
        "P3_UI_UX",
        "P4_COMPREHENSIVE_REGRESSION",
        "P5_UPSTREAM_DELTA",
        "P6_CLEAN_WINDOWS",
    ]
    for block in required_blocks:
        assert block in blocked_by, f"Missing required blocker: {block}"

    assert evidence_data.get("P0_GATE_CANDIDATE") == "PASS"
    assert evidence_data.get("independent_review") == "AWAITING"

    report_file = REPO_ROOT / "docs/audits/V2_2_RC2_HARDENING_REPORT.md"
    assert report_file.exists()
    report_content = report_file.read_text(encoding="utf-8")

    assert "RC2_READY: FALSE" in report_content or "rc2_ready: false" in report_content.lower()
    assert "P0_GATE_CANDIDATE: PASS" in report_content
