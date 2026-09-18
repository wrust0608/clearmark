"""tests/test_p0_round4_eocd_final.py

P0 Round 4 Final Micro-Corrective Test Suite:
- Robust EOCD locator ignoring candidate signatures embedded inside ZIP comments.
- Exact archive boundary validation (no trailing data or boundary overflow).
- Byte-for-byte preservation of binary and magic-containing comments across rebuild.
- Independent format fidelity validator invariants detecting archive-level comment drift.
- Complete agreement between security preflight and native package parsers on EOCD boundary.
"""

from __future__ import annotations

import io
import struct
import zipfile
import pytest

from service.scripts.zip_utils import locate_zip_eocd, ZipEocdError
from service.scripts.security import preflight_zip_container, SecurityViolation

from service.scripts.docx.package import DocxPackage, DocxFidelityException
from service.scripts.docx.validator import DocxFidelityValidator
from service.scripts.docx.mutation_plan import DocxMutationPlan

from service.scripts.xlsx.package import XlsxPackage, XlsxFidelityException
from service.scripts.xlsx.validator import XlsxFidelityValidator

from service.scripts.pptx.package import PptxPackage, PptxCorruptedPackageError
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
                b"<w:body><w:p><w:r><w:t>Round4 Test</w:t></w:r></w:p></w:body></w:document>",
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


# -----------------------------------------------------------------------------
# 1. EOCD Locator Ignores Magic Inside Comment (DOCX, XLSX, PPTX)
# -----------------------------------------------------------------------------


def test_docx_eocd_locator_ignores_magic_inside_comment():
    """Verify DOCX package parser correctly locates EOCD when comment contains PK0506."""
    comment = b"before-PK\x05\x06-after"
    data = _build_test_package("docx", comment=comment)

    # Security preflight accepts archive as structurally valid
    sec_result = preflight_zip_container(data)
    assert sec_result.is_safe is True

    # Native package parser correctly loads and preserves comment
    pkg = DocxPackage(data)
    assert pkg.get_archive_comment() == comment

    # Rebuilt archive preserves the exact comment byte-for-byte
    rebuilt = pkg.rebuild(changed_parts={"word/document.xml": b"<w:document><w:body/></w:document>"})
    pkg_rebuilt = DocxPackage(rebuilt)
    assert pkg_rebuilt.get_archive_comment() == comment


def test_xlsx_eocd_locator_ignores_magic_inside_comment():
    """Verify XLSX package parser correctly locates EOCD when comment contains PK0506."""
    comment = b"before-PK\x05\x06-after"
    data = _build_test_package("xlsx", comment=comment)

    sec_result = preflight_zip_container(data)
    assert sec_result.is_safe is True

    pkg = XlsxPackage(data)
    assert pkg.get_archive_comment() == comment

    rebuilt = pkg.rebuild(changed_parts={"xl/workbook.xml": b"<workbook/>"})
    pkg_rebuilt = XlsxPackage(rebuilt)
    assert pkg_rebuilt.get_archive_comment() == comment


def test_pptx_eocd_locator_ignores_magic_inside_comment():
    """Verify PPTX package parser correctly locates EOCD when comment contains PK0506."""
    comment = b"before-PK\x05\x06-after"
    data = _build_test_package("pptx", comment=comment)

    sec_result = preflight_zip_container(data)
    assert sec_result.is_safe is True

    pkg = PptxPackage(data)
    assert pkg.get_archive_comment() == comment

    rebuilt = pkg.rebuild(changed_parts={"ppt/presentation.xml": b"<p:presentation/>"})
    pkg_rebuilt = PptxPackage(rebuilt)
    assert pkg_rebuilt.get_archive_comment() == comment


# -----------------------------------------------------------------------------
# 2. Multiple Fake Signatures & Binary Comments
# -----------------------------------------------------------------------------


def test_eocd_multiple_fake_signatures_in_comment():
    """Verify parser handles multiple embedded PK0506 signatures in archive comment."""
    multi_magic_comment = b"prefix-PK\x05\x06-middle-PK\x05\x06-another-PK\x05\x06-suffix"

    for doc_type, cls in [("docx", DocxPackage), ("xlsx", XlsxPackage), ("pptx", PptxPackage)]:
        data = _build_test_package(doc_type, comment=multi_magic_comment)

        sec_res = preflight_zip_container(data)
        assert sec_res.is_safe is True

        pkg = cls(data)
        assert pkg.get_archive_comment() == multi_magic_comment

        part_name = "word/document.xml" if doc_type == "docx" else ("xl/workbook.xml" if doc_type == "xlsx" else "ppt/presentation.xml")
        rebuilt = pkg.rebuild(changed_parts={part_name: b"<updated/>"})
        rebuilt_pkg = cls(rebuilt)
        assert rebuilt_pkg.get_archive_comment() == multi_magic_comment


def test_eocd_binary_comment_roundtrip():
    """Verify non-UTF8 binary comment with nulls and magic roundtrips byte-for-byte."""
    binary_comment = b"\x00\xff\xfe\x00PK\x05\x06\xaa\xbb\xcc\xdd\x00\x01\x02"

    for doc_type, cls in [("docx", DocxPackage), ("xlsx", XlsxPackage), ("pptx", PptxPackage)]:
        data = _build_test_package(doc_type, comment=binary_comment)

        sec_res = preflight_zip_container(data)
        assert sec_res.is_safe is True

        pkg = cls(data)
        assert pkg.get_archive_comment() == binary_comment

        part_name = "word/document.xml" if doc_type == "docx" else ("xl/workbook.xml" if doc_type == "xlsx" else "ppt/presentation.xml")
        rebuilt = pkg.rebuild(changed_parts={part_name: b"<updated/>"})
        rebuilt_pkg = cls(rebuilt)
        assert rebuilt_pkg.get_archive_comment() == binary_comment


# -----------------------------------------------------------------------------
# 3. Exact Archive Boundary Validation
# -----------------------------------------------------------------------------


def test_eocd_requires_exact_archive_boundary():
    """Verify trailing bytes or malformed comment lengths fail closed."""
    base_data = _build_test_package("docx", comment=b"VALID_COMMENT")

    # Case A: Trailing bytes appended after declared comment boundary
    trailing_data = base_data + b"EXTRA_UNTRACKED_BYTES"

    with pytest.raises(ZipEocdError, match="malformed EOCD comment length or trailing data"):
        locate_zip_eocd(trailing_data)

    with pytest.raises(SecurityViolation):
        preflight_zip_container(trailing_data)

    with pytest.raises(DocxFidelityException):
        DocxPackage(trailing_data)

    # Case B: Malformed comment length exceeding archive size
    bad_len_buf = bytearray(base_data)
    idx, _, _ = locate_zip_eocd(base_data)
    struct.pack_into("<H", bad_len_buf, idx + 20, 60000)
    bad_len_data = bytes(bad_len_buf)

    with pytest.raises(ZipEocdError, match="malformed EOCD comment length or trailing data"):
        locate_zip_eocd(bad_len_data)

    with pytest.raises(SecurityViolation):
        preflight_zip_container(bad_len_data)

    with pytest.raises(DocxFidelityException):
        DocxPackage(bad_len_data)


# -----------------------------------------------------------------------------
# 4. Negative Validator Witnesses (Archive Comment Drift Rejection)
# -----------------------------------------------------------------------------


def test_docx_validator_rejects_archive_comment_drift():
    """Verify DocxFidelityValidator independently fails when archive comment drifts."""
    orig_data = _build_test_package("docx", comment=b"ORIGINAL")
    cand_data = _build_test_package("docx", comment=b"CHANGED")

    plan = DocxMutationPlan()
    validator = DocxFidelityValidator(orig_data, cand_data, plan)

    with pytest.raises(DocxFidelityException, match="archive-level ZIP comment drift"):
        validator.validate()


def test_xlsx_validator_rejects_archive_comment_drift():
    """Verify XlsxFidelityValidator independently fails when archive comment drifts."""
    orig_pkg = XlsxPackage(_build_test_package("xlsx", comment=b"ORIGINAL"))
    cand_pkg = XlsxPackage(_build_test_package("xlsx", comment=b"CHANGED"))

    validator = XlsxFidelityValidator(orig_pkg, cand_pkg, planned_changed_parts=set())
    report = validator.validate()

    assert report.passed is False
    assert any("archive-level ZIP comment drift" in err for err in report.errors)


def test_pptx_validator_rejects_archive_comment_drift():
    """Verify PptxFidelityValidator independently fails when archive comment drifts."""
    orig_pkg = PptxPackage(_build_test_package("pptx", comment=b"ORIGINAL"))
    cand_pkg = PptxPackage(_build_test_package("pptx", comment=b"CHANGED"))

    validator = PptxFidelityValidator(orig_pkg, cand_pkg, planned_changed_parts=set())
    report = validator.validate()

    assert report.passed is False
    assert any("archive-level ZIP comment drift" in err for err in report.errors)


# -----------------------------------------------------------------------------
# 5. Security Preflight and Native Parser Agreement
# -----------------------------------------------------------------------------


def test_security_preflight_and_native_parser_agree_on_eocd():
    """Verify security preflight and native OOXML parsers agree on EOCD location and comment."""
    test_cases = [
        ("empty", b""),
        ("ascii", b"ClearMark Provenance Record"),
        ("magic", b"head-PK\x05\x06-tail"),
        ("binary", b"\x01\x02\x03PK\x05\x06\xff\xfe\x00"),
    ]

    for label, comment in test_cases:
        for doc_type, cls in [("docx", DocxPackage), ("xlsx", XlsxPackage), ("pptx", PptxPackage)]:
            data = _build_test_package(doc_type, comment=comment)

            # 1. Security preflight passes
            sec_res = preflight_zip_container(data)
            assert sec_res.is_safe is True

            # 2. Canonical locator
            offset, clen, cbytes = locate_zip_eocd(data)
            assert cbytes == comment
            assert clen == len(comment)
            assert offset + 22 + clen == len(data)

            # 3. Native package parser
            pkg = cls(data)
            assert pkg.get_archive_comment() == comment
            assert pkg.get_archive_comment() == cbytes
