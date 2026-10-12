"""tests/test_p0_round5_eocd_candidate_validation.py

P0 Round 5 Final Micro-Corrective Test Suite:
- Robust EOCD resolution: structurally validates Central Directory before accepting candidates.
- Rejects candidate EOCDs embedded in comments even when they match the archive boundary.
- Verifies DOCX, XLSX, PPTX, and Security Preflight ignore boundary-matching fake EOCD records.
- Verifies rejection of CD size mismatch, entry count mismatch, and CD record overflow.
- Verifies trailing bytes fail closed.
- Verifies issue register semantic consistency (A19-A25 reserved for P1).
"""

from __future__ import annotations

import io
import json
import re
import struct
import zipfile
from pathlib import Path
import pytest

from service.scripts.zip_utils import locate_zip_eocd, ZipEocdError, ZipEocdInfo
from service.scripts.security import preflight_zip_container

from service.scripts.docx.package import DocxPackage
from service.scripts.docx.validator import DocxFidelityValidator
from service.scripts.docx.mutation_plan import DocxMutationPlan

from service.scripts.xlsx.package import XlsxPackage
from service.scripts.xlsx.validator import XlsxFidelityValidator

from service.scripts.pptx.package import PptxPackage
from service.scripts.pptx.validator import PptxFidelityValidator


def _build_test_package(doc_type: str, comment: bytes = b"") -> bytes:
    """Build a minimal valid OOXML package with an explicit raw EOCD comment."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        zf.writestr(
            "_rels/.rels",
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        if doc_type == "docx":
            zf.writestr(
                "word/document.xml",
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"<w:body><w:p><w:r><w:t>Round5 Test</w:t></w:r></w:p></w:body></w:document>",
            )
        elif doc_type == "xlsx":
            zf.writestr(
                "xl/workbook.xml",
                b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
            )
        elif doc_type == "pptx":
            zf.writestr(
                "ppt/presentation.xml",
                b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
            )

    raw = buf.getvalue()
    eocd_idx = raw.rfind(b"PK\x05\x06")
    cd_and_before = raw[:eocd_idx]
    eocd_rec = bytearray(raw[eocd_idx : eocd_idx + 22])
    eocd_rec[20:22] = struct.pack("<H", len(comment))
    return cd_and_before + bytes(eocd_rec) + comment


def _build_package_with_fake_eocd_comment(
    doc_type: str,
    fake_cd_size: int = 12345,
    fake_cd_offset: int = 67890,
    fake_entries: int = 1,
) -> tuple[bytes, int, int, bytes]:
    """Construct a valid package whose archive comment contains a boundary-matching fake EOCD.

    Returns:
        (crafted_archive_bytes, real_eocd_offset, fake_eocd_offset, full_real_comment)
    """
    base_data = _build_test_package(doc_type, comment=b"")
    real_eocd_offset = base_data.rfind(b"PK\x05\x06")
    sig, disk, cd_disk, disk_entries, total_entries, cd_size, cd_offset, _ = struct.unpack(
        "<4sHHHHIIH", base_data[real_eocd_offset : real_eocd_offset + 22]
    )

    prefix = b"comment-prefix-before-fake-"
    suffix = b"-comment-suffix-after-fake"

    # fake_offset = real_eocd_offset + 22 + len(prefix)
    # len(crafted) = real_eocd_offset + 22 + len(full_comment)
    # len(crafted) - (fake_offset + 22) = len(suffix)
    # Therefore fake_comment_len = len(suffix) guarantees boundary match
    fake_comment_len = len(suffix)
    fake_eocd_rec = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0,
        0,
        fake_entries,
        fake_entries,
        fake_cd_size,
        fake_cd_offset,
        fake_comment_len,
    )
    full_comment = prefix + fake_eocd_rec + suffix

    new_real_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        disk,
        cd_disk,
        disk_entries,
        total_entries,
        cd_size,
        cd_offset,
        len(full_comment),
    )
    crafted = base_data[:real_eocd_offset] + new_real_eocd + full_comment
    fake_eocd_offset = real_eocd_offset + 22 + len(prefix)

    # Invariant: fake_offset + 22 + fake_comment_len == len(crafted)
    assert fake_eocd_offset + 22 + fake_comment_len == len(crafted)
    return crafted, real_eocd_offset, fake_eocd_offset, full_comment


# -----------------------------------------------------------------------------
# 1. Self-Consistent Fake EOCD in Comment Ignored; Real EOCD Selected
# -----------------------------------------------------------------------------


def test_eocd_comment_with_self_consistent_fake_eocd_uses_real_record():
    """Verify locate_zip_eocd selects the real EOCD and ignores boundary-matching fake EOCD in comment."""
    data, real_offset, fake_offset, full_comment = _build_package_with_fake_eocd_comment("docx")

    # The fake candidate is later in the file than the real candidate
    assert fake_offset > real_offset

    info = locate_zip_eocd(data)
    assert isinstance(info, ZipEocdInfo)
    assert info.offset == real_offset
    assert info.offset != fake_offset
    assert info.comment == full_comment
    assert info.comment_length == len(full_comment)


def test_security_ignores_structurally_invalid_later_eocd_candidate():
    """Verify security preflight parses real container and is not misled by fake EOCD in comment."""
    data, real_offset, fake_offset, _ = _build_package_with_fake_eocd_comment("docx")
    result = preflight_zip_container(data)
    assert result.is_safe is True

    # Confirm locate_zip_eocd independently agreed on real EOCD offset
    info = locate_zip_eocd(data)
    assert info.offset == real_offset
    assert info.offset != fake_offset


def test_docx_ignores_structurally_invalid_later_eocd_candidate():
    """Verify DocxPackage ignores fake EOCD in comment, retains comment, and passes validation."""
    data, real_offset, fake_offset, comment = _build_package_with_fake_eocd_comment("docx")
    pkg = DocxPackage(data)
    assert pkg.get_archive_comment() == comment

    rebuilt = pkg.rebuild({})
    rebuilt_info = locate_zip_eocd(rebuilt)
    assert rebuilt_info.comment == comment

    val = DocxFidelityValidator(data, rebuilt, DocxMutationPlan())
    report = val.validate()
    assert report.get("visible_text_exact_match") is True


def test_xlsx_ignores_structurally_invalid_later_eocd_candidate():
    """Verify XlsxPackage ignores fake EOCD in comment, retains comment, and passes validation."""
    data, real_offset, fake_offset, comment = _build_package_with_fake_eocd_comment("xlsx")
    pkg = XlsxPackage(data)
    assert pkg.get_archive_comment() == comment

    rebuilt = pkg.rebuild({})
    rebuilt_info = locate_zip_eocd(rebuilt)
    assert rebuilt_info.comment == comment

    val = XlsxFidelityValidator(data, rebuilt, planned_changed_parts=set())
    res = val.validate()
    assert res.passed is True


def test_pptx_ignores_structurally_invalid_later_eocd_candidate():
    """Verify PptxPackage ignores fake EOCD in comment, retains comment, and passes validation."""
    data, real_offset, fake_offset, comment = _build_package_with_fake_eocd_comment("pptx")
    pkg = PptxPackage(data)
    assert pkg.get_archive_comment() == comment

    rebuilt = pkg.rebuild({})
    rebuilt_info = locate_zip_eocd(rebuilt)
    assert rebuilt_info.comment == comment

    val = PptxFidelityValidator(data, rebuilt)
    res = val.validate()
    assert res.passed is True


# -----------------------------------------------------------------------------
# 2. Multiple Boundary-Matching Fake EOCD Candidates
# -----------------------------------------------------------------------------


def test_multiple_boundary_matching_fake_eocd_candidates():
    """Verify locate_zip_eocd scans past multiple boundary-matching fake EOCDs to find real EOCD."""
    base_data = _build_test_package("docx", comment=b"")
    real_offset = base_data.rfind(b"PK\x05\x06")
    sig, disk, cd_disk, disk_entries, total_entries, cd_size, cd_offset, _ = struct.unpack(
        "<4sHHHHIIH", base_data[real_offset : real_offset + 22]
    )

    prefix = b"prefix-seg-"
    mid = b"-middle-seg-"
    suffix = b"-suffix-seg"

    # Fake 2 is closest to end of file
    fake2_comment_len = len(suffix)
    fake2 = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, total_entries, total_entries, 999, 999, fake2_comment_len)

    # Fake 1 is in between prefix and mid
    fake1_comment_len = len(mid) + len(fake2) + len(suffix)
    fake1 = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, total_entries, total_entries, 888, 888, fake1_comment_len)

    full_comment = prefix + fake1 + mid + fake2 + suffix
    new_real_eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        disk,
        cd_disk,
        disk_entries,
        total_entries,
        cd_size,
        cd_offset,
        len(full_comment),
    )
    crafted = base_data[:real_offset] + new_real_eocd + full_comment

    info = locate_zip_eocd(crafted)
    assert info.offset == real_offset
    assert info.comment == full_comment


# -----------------------------------------------------------------------------
# 3. Structural Central Directory Rejections
# -----------------------------------------------------------------------------


def test_candidate_cd_size_mismatch_rejected():
    """Verify that if an archive's EOCD declares a cd_size not ending at the EOCD offset, it is rejected."""
    base_data = _build_test_package("docx", comment=b"")
    real_offset = base_data.rfind(b"PK\x05\x06")
    sig, disk, cd_disk, disk_entries, total_entries, cd_size, cd_offset, comment_len = struct.unpack(
        "<4sHHHHIIH", base_data[real_offset : real_offset + 22]
    )

    # Corrupt cd_size so cd_offset + cd_size != real_offset
    corrupt_eocd = struct.pack(
        "<4sHHHHIIH",
        sig,
        disk,
        cd_disk,
        disk_entries,
        total_entries,
        cd_size - 10,  # size mismatch
        cd_offset,
        comment_len,
    )
    corrupted = base_data[:real_offset] + corrupt_eocd + base_data[real_offset + 22 :]

    with pytest.raises(ZipEocdError, match="failed structural validation"):
        locate_zip_eocd(corrupted)


def test_candidate_cd_entry_count_mismatch_rejected():
    """Verify that if EOCD declares more entries than present in Central Directory, it is rejected."""
    base_data = _build_test_package("docx", comment=b"")
    real_offset = base_data.rfind(b"PK\x05\x06")
    sig, disk, cd_disk, disk_entries, total_entries, cd_size, cd_offset, comment_len = struct.unpack(
        "<4sHHHHIIH", base_data[real_offset : real_offset + 22]
    )

    # Corrupt total_entries so it claims more entries than exist
    corrupt_eocd = struct.pack(
        "<4sHHHHIIH",
        sig,
        disk,
        cd_disk,
        disk_entries + 5,
        total_entries + 5,  # count mismatch
        cd_size,
        cd_offset,
        comment_len,
    )
    corrupted = base_data[:real_offset] + corrupt_eocd + base_data[real_offset + 22 :]

    with pytest.raises(ZipEocdError, match="failed structural validation"):
        locate_zip_eocd(corrupted)


def test_candidate_cd_record_overflow_rejected():
    """Verify that a corrupted CD record claiming extra/filename length beyond CD bounds is rejected."""
    base_data = _build_test_package("docx", comment=b"")
    real_offset = base_data.rfind(b"PK\x05\x06")
    sig, disk, cd_disk, disk_entries, total_entries, cd_size, cd_offset, comment_len = struct.unpack(
        "<4sHHHHIIH", base_data[real_offset : real_offset + 22]
    )

    # Corrupt the first CD record's filename length to overflow the CD buffer
    corrupted = bytearray(base_data)
    # Filename length in CD record is at cd_offset + 28
    corrupted[cd_offset + 28 : cd_offset + 30] = struct.pack("<H", 0xFF00)

    with pytest.raises(ZipEocdError, match="failed structural validation"):
        locate_zip_eocd(bytes(corrupted))


def test_real_eocd_with_binary_comment_still_roundtrips():
    """Verify that genuine binary comments with zero bytes and non-UTF8 bytes roundtrip cleanly."""
    binary_comment = b"\xff\x00\xfe\x00\x01\x02\x03"
    data = _build_test_package("docx", comment=binary_comment)

    info = locate_zip_eocd(data)
    assert info.comment == binary_comment

    pkg = DocxPackage(data)
    assert pkg.get_archive_comment() == binary_comment
    rebuilt = pkg.rebuild({})
    rebuilt_info = locate_zip_eocd(rebuilt)
    assert rebuilt_info.comment == binary_comment


def test_trailing_bytes_still_fail_closed():
    """Verify that arbitrary trailing bytes after declared archive comment fail closed."""
    data = _build_test_package("docx", comment=b"CLEAN_COMMENT")
    trailing_data = data + b"GARBAGE_TRAILING_BYTES"

    with pytest.raises(ZipEocdError, match="malformed EOCD comment length or trailing data"):
        locate_zip_eocd(trailing_data)


# -----------------------------------------------------------------------------
# 4. Issue Register Semantic Consistency (A19-A25 Reserved for P1)
# -----------------------------------------------------------------------------


def test_evidence_issue_register_semantic_consistency():
    """Verify evidence JSON and markdown report maintain exact issue register semantics.

    Invariants:
    1. A19-A25 are reserved for P1 and must NOT be present in P0 evidence issues.
    2. Issues in P0 evidence are strictly A01 through A18.
    3. Every issue key in evidence has matching severity and status in report markdown table.
    4. rc2_ready is strictly False.
    5. P1_STATISTICAL_WATERMARK is listed in rc2_blocked_by.
    """
    root_dir = Path(__file__).resolve().parent.parent
    evidence_path = root_dir / "docs" / "audits" / "V2_2_RC2_HARDENING_EVIDENCE.json"
    report_path = root_dir / "docs" / "audits" / "V2_2_RC2_HARDENING_REPORT.md"

    assert evidence_path.is_file(), f"Evidence file missing at {evidence_path}"
    assert report_path.is_file(), f"Report file missing at {report_path}"

    with open(evidence_path, "r", encoding="utf-8") as f:
        evidence = json.load(f)

    # Check readiness and blocker invariants
    assert evidence.get("rc2_ready") is False, "rc2_ready must be false before all phases complete"
    blocked_by = evidence.get("rc2_blocked_by", [])
    assert "P1_STATISTICAL_WATERMARK" in blocked_by, "P1 must be listed in rc2_blocked_by"

    # Check reserved issue keys A19-A25 are absent
    issues = evidence.get("issues", {})
    for reserved_id in [f"A{i:02d}" for i in range(19, 26)]:
        assert reserved_id not in issues, (
            f"Reserved issue identifier {reserved_id} must not exist in P0 evidence (reserved for P1)"
        )

    # Check expected P0 issue set is exactly A01..A18
    expected_p0_ids = [f"A{i:02d}" for i in range(1, 19)]
    assert sorted(issues.keys()) == expected_p0_ids, f"P0 issues must be exactly A01..A18, got {sorted(issues.keys())}"

    # Verify severity and status match between Evidence JSON and Markdown Report Table
    report_text = report_path.read_text(encoding="utf-8")

    # Regex to extract Markdown table rows: | **Axx** | S(1|2|3) | (FIXED|MITIGATED / FIDELITY-SAFE) |
    row_pattern = re.compile(r"\|\s*\*\*(A\d{2})\*\*\s*\|\s*(S[1-3])\s*\|\s*([^\|]+?)\s*\|")
    report_issues = {}
    for match in row_pattern.finditer(report_text):
        issue_id = match.group(1).replace("*", "").strip()
        sev = match.group(2).replace("*", "").strip()
        status = match.group(3).replace("*", "").strip()
        report_issues[issue_id] = {"severity": sev, "status": status}

    for issue_id in expected_p0_ids:
        assert issue_id in report_issues, f"Issue {issue_id} missing from report matrix table"
        ev_issue = issues[issue_id]
        rep_issue = report_issues[issue_id]
        assert ev_issue["severity"] == rep_issue["severity"], (
            f"Severity mismatch for {issue_id}: evidence={ev_issue['severity']} vs report={rep_issue['severity']}"
        )
        assert ev_issue["status"] == rep_issue["status"], (
            f"Status mismatch for {issue_id}: evidence={ev_issue['status']} vs report={rep_issue['status']}"
        )
