"""Tests for Phase 6: Protecting Non-Text Word Objects and Advanced Structural Elements."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
import pytest

from service.scripts.docx import clean_docx_lossless, extract_canonical_visible_text
from service.scripts.docx.package import DocxPackage

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def _build_complex_docx_with_objects() -> bytes:
    """Build a DOCX containing tables, bookmarks, drawings, field codes, and track changes."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:wp="{WP_NS}">
  <w:body>
    <!-- 1. Heading with Bookmark -->
    <w:p>
      <w:bookmarkStart w:id="0" w:name="SectionTitle"/>
      <w:r><w:t>Tiêu đề\u200Bchính</w:t></w:r>
      <w:bookmarkEnd w:id="0"/>
    </w:p>

    <!-- 2. Complex Table -->
    <w:tbl>
      <w:tblPr><w:tblW w:w="5000" w:type="dxa"/></w:tblPr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Cột 1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Cột 2\uFEFF(Ẩn)</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Dữ liệu 1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Dữ liệu 2</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>

    <!-- 3. Drawing / Shape Object -->
    <w:p>
      <w:r>
        <w:drawing>
          <wp:inline distT="0" distB="0" distL="0" distR="0">
            <wp:extent cx="1000000" cy="500000"/>
            <wp:docPr id="1" name="Picture 1"/>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>

    <!-- 4. Field Code (PAGE number) -->
    <w:p>
      <w:r><w:t>Trang số </w:t></w:r>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>1</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>

    <!-- 5. Track changes (ins and del) -->
    <w:p>
      <w:r><w:t>Văn bản gốc </w:t></w:r>
      <w:ins w:id="1" w:author="Reviewer" w:date="2026-01-01T00:00:00Z">
        <w:r><w:t>phần thêm mới</w:t></w:r>
      </w:ins>
      <w:del w:id="2" w:author="Reviewer" w:date="2026-01-01T00:00:00Z">
        <w:r><w:delText>phần bị xóa</w:delText></w:r>
      </w:del>
    </w:p>

    <!-- 6. Isolated Carrier in its own run: must preserve empty <w:t></w:t> to keep run count invariant -->
    <w:p>
      <w:r><w:t>Trước</w:t></w:r>
      <w:r><w:t>\u200B</w:t></w:r>
      <w:r><w:t>Sau</w:t></w:r>
    </w:p>

    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
  </w:body>
</w:document>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def test_table_structure_and_counts_preserved():
    """Verify tables, rows, and cells are 100% preserved."""
    raw = _build_complex_docx_with_objects()
    cleaned, report = clean_docx_lossless(raw)

    pkg_orig = DocxPackage(raw)
    pkg_clean = DocxPackage(cleaned)

    root_o = ET.fromstring(pkg_orig.get_member("word/document.xml"))
    root_c = ET.fromstring(pkg_clean.get_member("word/document.xml"))

    assert len(root_o.findall(f".//{{{W_NS}}}tbl")) == len(root_c.findall(f".//{{{W_NS}}}tbl")) == 1
    assert len(root_o.findall(f".//{{{W_NS}}}tr")) == len(root_c.findall(f".//{{{W_NS}}}tr")) == 2
    assert len(root_o.findall(f".//{{{W_NS}}}tc")) == len(root_c.findall(f".//{{{W_NS}}}tc")) == 4


def test_bookmarks_preserved():
    """Verify bookmarkStart and bookmarkEnd IDs and names are preserved."""
    raw = _build_complex_docx_with_objects()
    cleaned, report = clean_docx_lossless(raw)

    pkg_clean = DocxPackage(cleaned)
    root_c = ET.fromstring(pkg_clean.get_member("word/document.xml"))

    bm_starts = root_c.findall(f".//{{{W_NS}}}bookmarkStart")
    bm_ends = root_c.findall(f".//{{{W_NS}}}bookmarkEnd")

    assert len(bm_starts) == 1
    assert len(bm_ends) == 1
    assert bm_starts[0].attrib.get(f"{{{W_NS}}}name") == "SectionTitle"
    assert bm_starts[0].attrib.get(f"{{{W_NS}}}id") == "0"
    assert bm_ends[0].attrib.get(f"{{{W_NS}}}id") == "0"


def test_drawings_and_shapes_preserved():
    """Verify drawing and picture objects are preserved."""
    raw = _build_complex_docx_with_objects()
    cleaned, report = clean_docx_lossless(raw)

    pkg_clean = DocxPackage(cleaned)
    root_c = ET.fromstring(pkg_clean.get_member("word/document.xml"))

    drawings = root_c.findall(f".//{{{W_NS}}}drawing")
    assert len(drawings) == 1
    inlines = drawings[0].findall(f".//{{{WP_NS}}}inline")
    assert len(inlines) == 1


def test_field_codes_preserved():
    """Verify instrText field codes (like PAGE) are never touched."""
    raw = _build_complex_docx_with_objects()
    cleaned, report = clean_docx_lossless(raw)

    pkg_clean = DocxPackage(cleaned)
    root_c = ET.fromstring(pkg_clean.get_member("word/document.xml"))

    instrs = root_c.findall(f".//{{{W_NS}}}instrText")
    assert len(instrs) == 1
    assert instrs[0].text == " PAGE "


def test_track_changes_preserved():
    """Verify track changes (<w:ins> and <w:del>) remain intact."""
    raw = _build_complex_docx_with_objects()
    cleaned, report = clean_docx_lossless(raw)

    pkg_clean = DocxPackage(cleaned)
    root_c = ET.fromstring(pkg_clean.get_member("word/document.xml"))

    ins_elems = root_c.findall(f".//{{{W_NS}}}ins")
    del_elems = root_c.findall(f".//{{{W_NS}}}del")
    assert len(ins_elems) == 1
    assert len(del_elems) == 1


def test_empty_run_preserved_and_run_count_invariant():
    """Verify that when a carrier inside a run is deleted, the run is kept (empty <w:t></w:t>)."""
    raw = _build_complex_docx_with_objects()
    cleaned, report = clean_docx_lossless(raw)

    pkg_orig = DocxPackage(raw)
    pkg_clean = DocxPackage(cleaned)

    root_o = ET.fromstring(pkg_orig.get_member("word/document.xml"))
    root_c = ET.fromstring(pkg_clean.get_member("word/document.xml"))

    runs_o = root_o.findall(f".//{{{W_NS}}}r")
    runs_c = root_c.findall(f".//{{{W_NS}}}r")

    # Run count must NOT change!
    assert len(runs_o) == len(runs_c)


def test_whitespace_edge_preserves_xml_space():
    """Verify that edge whitespace in runs automatically receives xml:space='preserve'."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:r><w:t> Quản lý\u200B </w:t></w:r>
    </w:p>
  </w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")

    cleaned, report = clean_docx_lossless(buf.getvalue())
    pkg_clean = DocxPackage(cleaned)
    clean_xml = pkg_clean.get_member("word/document.xml").decode("utf-8")

    assert 'xml:space="preserve"' in clean_xml
    assert "Quản lý" in clean_xml
    assert "\u200B" not in clean_xml
