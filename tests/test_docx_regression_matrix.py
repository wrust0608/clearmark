"""Tests for Phase 12: Comprehensive 30+ Scenario DOCX Regression Matrix."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
import pytest

from service.scripts.docx import (
    clean_docx_lossless,
    extract_canonical_visible_text,
    DocxPackage,
    DocxFidelityValidator,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _wrap_docx(parts: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for name, content in parts.items():
            if isinstance(content, str):
                zf.writestr(name, content.encode("utf-8"))
            else:
                zf.writestr(name, content)
    return buf.getvalue()


# 1. Vietnamese NFC vs NFD preservation
def test_matrix_01_vietnamese_diacritics_nfc_nfd():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Nhiệm vụ quản lý\u200Btài liệu Tiếng Việt</w:t></w:r></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert text == "Nhiệm vụ quản lýtài liệu Tiếng Việt"


# 2. Non-breaking space (U+00A0) and narrow non-breaking space (U+202F) invariant
def test_matrix_02_nbsp_and_nnbsp_preserved():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Số\u00A0123\u202Fkg\u200Bđo lường</w:t></w:r></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert text == "Số\u00A0123\u202Fkgđo lường"
    assert "\u00A0" in text
    assert "\u202F" in text


# 3. Non-break hyphen (w:noBreakHyphen) and soft hyphen (U+00AD)
def test_matrix_03_nobreakhyphen_and_softhyphen():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:r><w:t>ISO</w:t></w:r>
      <w:r><w:noBreakHyphen/></w:r>
      <w:r><w:t>IEC\u00AD29500</w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    # Soft hyphen U+00AD is an invisible carrier and stripped; noBreakHyphen is preserved as \u2011
    assert text == "ISO\u2011IEC29500"


# 4. Tab, line break, carriage return
def test_matrix_04_tab_break_carriage_return():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:r><w:t>Cột 1</w:t><w:tab/><w:t>Cột 2</w:t><w:br/><w:t>Dòng 2</w:t><w:cr/><w:t>Dòng 3</w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert text == "Cột 1\tCột 2\nDòng 2\nDòng 3"


# 5. Whitespace preservation with xml:space="preserve" on edges
def test_matrix_05_whitespace_edges_preserved():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:r><w:t> Từ đầu \u200B</w:t></w:r>
      <w:r><w:t>\u200B</w:t></w:r>
      <w:r><w:t> Từ cuối </w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert 'xml:space="preserve"' in clean_xml
    assert " Từ đầu " in clean_xml
    assert " Từ cuối " in clean_xml


# 6. Multiple split runs forming a compound word
def test_matrix_06_split_runs_compound_word():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:r><w:t>Quản</w:t></w:r>
      <w:r><w:t> </w:t></w:r>
      <w:r><w:t>lý\u200B</w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    # Must NOT become "Quảnlý"
    assert text == "Quản lý"


# 7. Empty run preservation when carrier is stripped
def test_matrix_07_empty_run_preserved():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:r><w:t>A</w:t></w:r>
      <w:r><w:t>\uFEFF</w:t></w:r>
      <w:r><w:t>B</w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    pkg = DocxPackage(clean)
    root = ET.fromstring(pkg.get_member("word/document.xml"))
    runs = root.findall(f".//{{{W_NS}}}r")
    assert len(runs) == 3


# 8. Paragraph properties (pPr) untouched
def test_matrix_08_paragraph_properties_untouched():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:pPr>
        <w:jc w:val="center"/>
        <w:spacing w:line="360" w:lineRule="auto" w:before="120" w:after="120"/>
        <w:ind w:left="720" w:right="720"/>
      </w:pPr>
      <w:r><w:t>Đoạn văn\u200Bcăn giữa</w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert '<w:jc w:val="center"/>' in clean_xml
    assert 'w:line="360"' in clean_xml


# 9. Run properties (rPr) untouched
def test_matrix_09_run_properties_untouched():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:r>
        <w:rPr>
          <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>
          <w:b/>
          <w:i/>
          <w:color w:val="FF0000"/>
          <w:sz w:val="28"/>
        </w:rPr>
        <w:t>In đậm\u200Bnghiêng đỏ</w:t>
      </w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert '<w:b/>' in clean_xml
    assert '<w:color w:val="FF0000"/>' in clean_xml


# 10. Nested tables (w:tbl inside w:tc)
def test_matrix_10_nested_tables():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:tbl>
      <w:tr>
        <w:tc>
          <w:p><w:r><w:t>Bảng ngoài</w:t></w:r></w:p>
          <w:tbl>
            <w:tr>
              <w:tc><w:p><w:r><w:t>Bảng trong\u200B1</w:t></w:r></w:p></w:tc>
            </w:tr>
          </w:tbl>
        </w:tc>
      </w:tr>
    </w:tbl>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    pkg = DocxPackage(clean)
    root = ET.fromstring(pkg.get_member("word/document.xml"))
    assert len(root.findall(f".//{{{W_NS}}}tbl")) == 2


# 11. Merged table cells (gridSpan and vMerge)
def test_matrix_11_merged_table_cells():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:tbl>
      <w:tr>
        <w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>Gộp ngang</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>Gộp dọc</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Ô thường\u200B</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert '<w:gridSpan w:val="2"/>' in clean_xml
    assert '<w:vMerge w:val="restart"/>' in clean_xml


# 12. Bookmarks across multiple paragraphs
def test_matrix_12_cross_paragraph_bookmarks():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:bookmarkStart w:id="1" w:name="LongBM"/><w:r><w:t>Bắt đầu\u200Bđoạn 1</w:t></w:r></w:p>
    <w:p><w:r><w:t>Giữa đoạn 2</w:t></w:r></w:p>
    <w:p><w:r><w:t>Cuối đoạn 3</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": xml})
    clean, rep = clean_docx_lossless(raw)
    pkg = DocxPackage(clean)
    root = ET.fromstring(pkg.get_member("word/document.xml"))
    assert len(root.findall(f".//{{{W_NS}}}bookmarkStart")) == 1
    assert len(root.findall(f".//{{{W_NS}}}bookmarkEnd")) == 1


# 13. External vs internal hyperlinks
def test_matrix_13_hyperlinks_internal_and_external():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:hyperlink r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
        <w:r><w:t>Liên kết\u200Bngoài</w:t></w:r>
      </w:hyperlink>
      <w:hyperlink w:anchor="MySection">
        <w:r><w:t>Liên kết trong</w:t></w:r>
      </w:hyperlink>
    </w:p>
    </w:body></w:document>"""
    rels = """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://google.com" TargetMode="External"/>
    </Relationships>"""
    raw = _wrap_docx({"word/document.xml": xml, "word/_rels/document.xml.rels": rels})
    clean, rep = clean_docx_lossless(raw)
    clean_rels = DocxPackage(clean).get_member("word/_rels/document.xml.rels").decode("utf-8")
    assert "https://google.com" in clean_rels
    assert 'TargetMode="External"' in clean_rels


# 14. Comments and comment range
def test_matrix_14_comments_range():
    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:commentRangeStart w:id="0"/>
      <w:r><w:t>Văn bản có comment\u200B</w:t></w:r>
      <w:commentRangeEnd w:id="0"/>
      <w:r><w:commentReference w:id="0"/></w:r>
    </w:p>
    </w:body></w:document>"""
    comments = f"""<?xml version="1.0"?><w:comments xmlns:w="{W_NS}">
    <w:comment w:id="0" w:author="User"><w:p><w:r><w:t>Nội dung nhận xét</w:t></w:r></w:p></w:comment>
    </w:comments>"""
    raw = _wrap_docx({"word/document.xml": xml, "word/comments.xml": comments})
    clean, rep = clean_docx_lossless(raw)
    clean_comments = DocxPackage(clean).get_member("word/comments.xml").decode("utf-8")
    assert "Nội dung nhận xét" in clean_comments


# 15. Footnotes and Endnotes
def test_matrix_15_footnotes_and_endnotes():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Văn bản chính\u200B</w:t></w:r></w:p>
    </w:body></w:document>"""
    footnotes_xml = f"""<?xml version="1.0"?><w:footnotes xmlns:w="{W_NS}">
    <w:footnote w:id="1"><w:p><w:r><w:t>Chú thích chân trang\u200B</w:t></w:r></w:p></w:footnote>
    </w:footnotes>"""
    raw = _wrap_docx({"word/document.xml": doc_xml, "word/footnotes.xml": footnotes_xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert "Văn bản chính" in text
    assert "Chú thích chân trang" in text
    assert "\u200B" not in text


# 16. Header and Footer
def test_matrix_16_headers_and_footers():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Nội dung thân</w:t></w:r></w:p>
    </w:body></w:document>"""
    header_xml = f"""<?xml version="1.0"?><w:hdr xmlns:w="{W_NS}">
    <w:p><w:r><w:t>Tiêu đề trang\u200B</w:t></w:r></w:p>
    </w:hdr>"""
    footer_xml = f"""<?xml version="1.0"?><w:ftr xmlns:w="{W_NS}">
    <w:p><w:r><w:t>Chân trang\u200B</w:t></w:r></w:p>
    </w:ftr>"""
    raw = _wrap_docx({
        "word/document.xml": doc_xml,
        "word/header1.xml": header_xml,
        "word/footer1.xml": footer_xml,
    })
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert "Tiêu đề trang" in text
    assert "Chân trang" in text
    assert "\u200B" not in text


# 17. Field codes: PAGE, NUMPAGES, DATE, TOC
def test_matrix_17_field_codes_page_date_toc():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>
      <w:r><w:instrText xml:space="preserve"> DATE \\@ "dd/MM/yyyy" </w:instrText></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert 'TOC \\o "1-3"' in clean_xml
    assert 'DATE \\@ "dd/MM/yyyy"' in clean_xml


# 18. Math equations (m:oMath)
def test_matrix_18_math_equations():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}" xmlns:m="{M_NS}"><w:body>
    <w:p>
      <m:oMathPara>
        <m:oMath>
          <m:r><m:t>E=mc^2</m:t></m:r>
        </m:oMath>
      </m:oMathPara>
      <w:r><w:t>Phương trình\u200BEinstein</w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert "<m:oMathPara>" in clean_xml
    assert "E=mc^2" in clean_xml


# 19. Drawings & Shapes
def test_matrix_19_inline_and_anchor_drawings():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}" xmlns:wp="{WP_NS}"><w:body>
    <w:p>
      <w:r>
        <w:drawing>
          <wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251658240" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">
            <wp:extent cx="2000000" cy="1000000"/>
            <wp:docPr id="10" name="Shape 10"/>
          </wp:anchor>
        </w:drawing>
      </w:r>
      <w:r><w:t>Ảnh minh họa\u200B</w:t></w:r>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert "<wp:anchor" in clean_xml
    assert 'name="Shape 10"' in clean_xml


# 20. Track changes: ins and delText
def test_matrix_20_track_changes_revisions():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p>
      <w:ins w:id="1" w:author="Author"><w:r><w:t>Được thêm\u200Bvào</w:t></w:r></w:ins>
      <w:del w:id="2" w:author="Author"><w:r><w:delText>Bị xóa đi</w:delText></w:r></w:del>
    </w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert "<w:ins" in clean_xml
    assert "<w:del" in clean_xml
    assert "<w:delText>Bị xóa đi</w:delText>" in clean_xml


# 21. CustomXml dropping and relationship pruning
def test_matrix_21_customxml_dropped_and_pruned():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Văn bản</w:t></w:r></w:p>
    </w:body></w:document>"""
    rels = """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="customXml/item1.xml"/>
    </Relationships>"""
    custom = "<root><data/></root>"
    raw = _wrap_docx({
        "word/document.xml": doc_xml,
        "_rels/.rels": rels,
        "customXml/item1.xml": custom,
    })
    clean, rep = clean_docx_lossless(raw)
    pkg = DocxPackage(clean)
    assert not pkg.has_member("customXml/item1.xml")
    clean_rels = pkg.get_member("_rels/.rels").decode("utf-8")
    assert "customXml/item1.xml" not in clean_rels


# 22. Metadata core scrubbing
def test_matrix_22_core_metadata_scrubbed():
    core = """<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:creator>John Doe &amp; Co</dc:creator>
    <cp:lastModifiedBy>Jane &lt;Editor&gt;</cp:lastModifiedBy>
    </cp:coreProperties>"""
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>Doc</w:t></w:r></w:p></w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml, "docProps/core.xml": core})
    clean, rep = clean_docx_lossless(raw)
    clean_core = DocxPackage(clean).get_member("docProps/core.xml").decode("utf-8")
    assert "<dc:creator></dc:creator>" in clean_core or "<dc:creator/>" in clean_core
    assert "<cp:lastModifiedBy></cp:lastModifiedBy>" in clean_core or "<cp:lastModifiedBy/>" in clean_core


# 23. App metadata AppVersion and TotalTime preserved
def test_matrix_23_app_props_system_fields_preserved():
    app = """<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
    <Application>Microsoft Word</Application>
    <AppVersion>16.0000</AppVersion>
    <TotalTime>120</TotalTime>
    <Pages>5</Pages>
    <Company>Corporation</Company>
    </Properties>"""
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>Doc</w:t></w:r></w:p></w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml, "docProps/app.xml": app})
    clean, rep = clean_docx_lossless(raw)
    clean_app = DocxPackage(clean).get_member("docProps/app.xml").decode("utf-8")
    assert "<AppVersion>16.0000</AppVersion>" in clean_app
    assert "<TotalTime>120</TotalTime>" in clean_app
    assert "<Company></Company>" in clean_app


# 24. Custom document properties dropped
def test_matrix_24_custom_props_dropped():
    custom = """<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"><property name="ClientID"><vt:lpwstr xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">12345</vt:lpwstr></property></Properties>"""
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>Doc</w:t></w:r></w:p></w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml, "docProps/custom.xml": custom})
    clean, rep = clean_docx_lossless(raw)
    pkg = DocxPackage(clean)
    assert not pkg.has_member("docProps/custom.xml")


# 25. Embedded media PNG cleaned in word/media/
def test_matrix_25_embedded_media_cleaned():
    png_with_text = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\x15tEXtComment\x00AI Watermark"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>Ảnh</w:t></w:r></w:p></w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml, "word/media/image1.png": png_with_text})
    clean, rep = clean_docx_lossless(raw)
    cleaned_png = DocxPackage(clean).get_member("word/media/image1.png")
    assert b"AI Watermark" not in cleaned_png
    assert cleaned_png.startswith(b"\x89PNG")


# 26. Complex Unicode Emoji Sequence (Family emoji with ZWJ)
def test_matrix_26_emoji_sequence_preserved():
    # 👨‍👩‍👧 = U+1F468 U+200D U+1F469 U+200D U+1F467
    family = "👨‍👩‍👧"
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Gia đình {family} hạnh phúc\u200B</w:t></w:r></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert family in text
    assert "\u200B" not in text


# 27. Complex scripts: Arabic and Devanagari ligatures
def test_matrix_27_complex_scripts_preserved():
    # Arabic word with ligatures and Devanagari
    arabic = "العربية"
    devanagari = "नमस्ते"
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>{arabic} và {devanagari}\u200B</w:t></w:r></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert arabic in text
    assert devanagari in text


# 28. Already clean document: Zero-copy pass-through
def test_matrix_28_already_clean_zero_copy():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Tài liệu hoàn toàn sạch</w:t></w:r></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    assert clean == raw
    assert rep["changed"] is False
    assert rep["mutations_count"] == 0


# 29. Idempotency: clean(clean(doc)) == clean(doc)
def test_matrix_29_idempotency():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Văn bản\u200Bthử nghiệm\uFEFFlần 1</w:t></w:r></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean1, rep1 = clean_docx_lossless(raw)
    clean2, rep2 = clean_docx_lossless(clean1)
    assert clean1 == clean2
    assert rep2["changed"] is False


# 30. Entity-encoded carriers (&#x200B; and &amp;)
def test_matrix_30_entity_encoded_carriers_and_symbols():
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>R&amp;D Team&#x200B;Vietnam</w:t></w:r></w:p>
    </w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    text = extract_canonical_visible_text(clean)
    assert text == "R&D TeamVietnam"
    clean_xml = DocxPackage(clean).get_member("word/document.xml").decode("utf-8")
    assert "R&amp;D Team" in clean_xml


# 31. Large document simulation (100 paragraphs with various runs)
def test_matrix_31_large_document_paragraphs():
    paras = []
    for i in range(100):
        paras.append(f"<w:p><w:r><w:t>Đoạn văn số {i}\u200Bnội dung chi tiết</w:t></w:r></w:p>")
    doc_xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>{''.join(paras)}</w:body></w:document>"""
    raw = _wrap_docx({"word/document.xml": doc_xml})
    clean, rep = clean_docx_lossless(raw)
    assert rep["changed"] is True
    assert rep["mutations_count"] == 100
    pkg = DocxPackage(clean)
    root = ET.fromstring(pkg.get_member("word/document.xml"))
    assert len(root.findall(f".//{{{W_NS}}}p")) == 100
