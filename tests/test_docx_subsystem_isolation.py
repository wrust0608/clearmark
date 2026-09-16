"""Tests for Phase 3: Lossless DOCX Subsystem Isolation and Canonical Extraction."""

from __future__ import annotations

import io
import sys
import zipfile
import pytest

from service.scripts.docx import (
    clean_docx_lossless,
    DocxDetector,
    DocxFidelityException,
    DocxFidelityValidator,
    DocxMutationPlan,
    DocxPackage,
    DocxPatcher,
    extract_canonical_visible_text,
    remove_planned_carriers,
)
from service.scripts.docx.visible_text import _extract_text_from_xml


def test_subsystem_has_no_ai_or_llm_dependencies():
    """Verify docx package imports zero AI/LLM libraries and has no references to statistical rewriters."""
    import docx
    import docx.cleaner
    import docx.detector
    import docx.mutation_plan
    import docx.package
    import docx.patcher
    import docx.validator
    import docx.visible_text

    forbidden_modules = [
        "ollama",
        "openai",
        "anthropic",
        "torch",
        "transformers",
        "tokenizers",
        "docx_statistical",
    ]

    for mod_name in forbidden_modules:
        assert mod_name not in sys.modules, f"Forbidden module {mod_name} was imported by docx subsystem!"

    # Check that docx modules have no forbidden attributes or functions
    for mod in (
        docx.cleaner,
        docx.detector,
        docx.mutation_plan,
        docx.package,
        docx.patcher,
        docx.validator,
        docx.visible_text,
    ):
        for attr in ("ollama", "qwen", "rewrite", "statistical", "llm"):
            assert not hasattr(mod, attr), f"Module {mod.__name__} has forbidden attribute {attr}"


def test_package_exports_clean_api():
    """Verify clean_docx_lossless and core components are cleanly exported."""
    expected_exports = [
        "clean_docx_lossless",
        "DocxDetector",
        "DocxFidelityException",
        "DocxFidelityValidator",
        "DocxMutationPlan",
        "DocxPackage",
        "DocxPatcher",
        "extract_canonical_visible_text",
        "remove_planned_carriers",
    ]
    import docx

    for export_name in expected_exports:
        assert hasattr(docx, export_name), f"docx is missing expected export {export_name}"


def test_canonical_text_extraction_separates_instrtext_and_rpr():
    """Ensure field codes (<w:instrText>) and run properties (<w:rPr>) are never extracted as text."""
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p>
          <w:pPr><w:jc w:val="center"/></w:pPr>
          <w:r>
            <w:rPr><w:b/><w:color w:val="FF0000"/><w:sz w:val="28"/></w:rPr>
            <w:t>Trang số </w:t>
          </w:r>
          <w:r>
            <w:fldChar w:fldCharType="begin"/>
          </w:r>
          <w:r>
            <w:instrText xml:space="preserve"> PAGE </w:instrText>
          </w:r>
          <w:r>
            <w:fldChar w:fldCharType="separate"/>
          </w:r>
          <w:r>
            <w:t>1</w:t>
          </w:r>
          <w:r>
            <w:fldChar w:fldCharType="end"/>
          </w:r>
        </w:p>
      </w:body>
    </w:document>
    """
    extracted = _extract_text_from_xml(xml)
    # The visible text must be "Trang số 1", NOT containing "PAGE" or "center" or "FF0000"
    assert "PAGE" not in extracted
    assert "center" not in extracted
    assert "FF0000" not in extracted
    assert extracted == "Trang số 1"


def test_canonical_text_extraction_special_characters():
    """Ensure tab, br, cr, and noBreakHyphen are faithfully extracted."""
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p>
          <w:r><w:t>Mục</w:t></w:r>
          <w:r><w:tab/></w:r>
          <w:r><w:t>Nội dung</w:t></w:r>
          <w:r><w:noBreakHyphen/></w:r>
          <w:r><w:t>Chi tiết</w:t></w:r>
          <w:r><w:br/></w:r>
          <w:r><w:t>Dòng tiếp theo</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>
    """
    extracted = _extract_text_from_xml(xml)
    assert extracted == "Mục\tNội dung\u2011Chi tiết\nDòng tiếp theo"


def test_canonical_text_extraction_tables_and_multi_parts():
    """Ensure text inside table cells and across multiple parts (document, header, footer) is canonical."""
    doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Tiêu đề chính</w:t></w:r></w:p>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>Ô A1</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Ô B1</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
      </w:body>
    </w:document>"""

    hdr_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:p><w:r><w:t>Header văn bản</w:t></w:r></w:p>
    </w:hdr>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("word/header1.xml", hdr_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")

    text = extract_canonical_visible_text(buf.getvalue())
    # word/document.xml comes first, then word/header1.xml
    expected_doc_text = "Tiêu đề chính\nÔ A1\nÔ B1"
    expected_hdr_text = "Header văn bản"
    assert text == f"{expected_doc_text}\n\n{expected_hdr_text}"
