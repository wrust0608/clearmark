"""Regression and fidelity tests for lossless DOCX watermark and metadata cleaning.

Ensures:
1. No word concatenation ("Quản lý" -> "Quảnlý").
2. No semantic/content rewrite ("Nhiệm vụ" -> "Mục đích").
3. Preservation of all formatting, runs, tables, and XML structures.
4. Default normalize_spaces = False (NBSP preserved).
5. Exact canonical visible text equality after removing target carriers.
6. Fail-closed behavior on fidelity failure.
"""

from __future__ import annotations

import io
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# Ensure scripts dir is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service" / "scripts"))


def make_test_docx(
    body_xml: str,
    core_xml: str = '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>',
    app_xml: str = '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>',
    custom_xml: str | None = None,
    extra_parts: dict[str, bytes | str] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body_xml}
  </w:body>
</w:document>""",
        )
        zf.writestr("docProps/core.xml", core_xml)
        zf.writestr("docProps/app.xml", app_xml)
        if custom_xml is not None:
            zf.writestr("customXml/item1.xml", custom_xml)
        if extra_parts:
            for k, v in extra_parts.items():
                if isinstance(v, str):
                    zf.writestr(k, v.encode("utf-8"))
                else:
                    zf.writestr(k, v)
    return buf.getvalue()


def test_regression_split_runs_space_loss():
    """Tái hiện chính xác bug: Quản lý chất lượng bị dính thành Quảnlý chấtlượng."""
    # Run structure where spaces are inside runs or separate space runs
    body_xml = """
    <w:p>
      <w:r><w:t>Quản</w:t></w:r>
      <w:r><w:t xml:space="preserve"> lý </w:t></w:r>
      <w:r><w:t>chất</w:t></w:r>
      <w:r><w:t xml:space="preserve"> lượng\u200B</w:t></w:r>
      <w:r><w:t xml:space="preserve"> bao </w:t></w:r>
      <w:r><w:t>gồm\u200B</w:t></w:r>
      <w:r><w:t xml:space="preserve"> việc </w:t></w:r>
      <w:r><w:t>kiểm</w:t></w:r>
      <w:r><w:t xml:space="preserve"> soát </w:t></w:r>
      <w:r><w:t>chất</w:t></w:r>
      <w:r><w:t xml:space="preserve"> lượng </w:t></w:r>
      <w:r><w:t>vật</w:t></w:r>
      <w:r><w:t xml:space="preserve"> tư </w:t></w:r>
      <w:r><w:t>đầu</w:t></w:r>
      <w:r><w:t xml:space="preserve"> vào.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)

    # Import clean_docx_lossless
    from docx import clean_docx_lossless, extract_canonical_visible_text

    cleaned_bytes, report = clean_docx_lossless(raw_docx)

    # Check visible text
    visible_before = extract_canonical_visible_text(raw_docx)
    visible_after = extract_canonical_visible_text(cleaned_bytes)

    # Must NOT have Quảnlý or chấtlượng
    assert "Quảnlý" not in visible_after
    assert "chấtlượng" not in visible_after
    assert "baogồm" not in visible_after
    assert "việckiểm" not in visible_after

    expected = "Quản lý chất lượng bao gồm việc kiểm soát chất lượng vật tư đầu vào."
    assert visible_after.strip() == expected


def test_regression_no_semantic_rewrite():
    """Không bao giờ cho phép AI / LLM viết lại nội dung (Nhiệm vụ -> Mục đích)."""
    text = "Nhiệm vụ quản lý không biến mất khi dự án chuyển giai đoạn mà thay đổi về nội dung và phương thức thực hiện:\u200B"
    body_xml = f"""
    <w:p>
      <w:r><w:t>{text}</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)

    from docx import clean_docx_lossless, extract_canonical_visible_text

    cleaned_bytes, report = clean_docx_lossless(raw_docx)
    visible_after = extract_canonical_visible_text(cleaned_bytes)

    assert "Mục đích quản lý không biến mất" not in visible_after
    assert "Nhiệm vụ quản lý không biến mất" in visible_after


def test_nbsp_preserved_by_default():
    """Mặc định normalize_spaces=False: U+00A0 (NBSP) và U+202F phải được giữ nguyên."""
    body_xml = """
    <w:p>
      <w:r><w:t xml:space="preserve">Điều\u00A01: Quy định\u202Fchung.\u200B</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)

    from docx import clean_docx_lossless, extract_canonical_visible_text

    cleaned_bytes, report = clean_docx_lossless(raw_docx)
    visible_after = extract_canonical_visible_text(cleaned_bytes)

    assert "\u00A0" in visible_after
    assert "\u202F" in visible_after
    assert "\u200B" not in visible_after


def test_structural_invariants_run_count():
    """Run count, paragraph count, and table count must remain 100% invariant."""
    body_xml = """
    <w:p>
      <w:r><w:t>Run 1</w:t></w:r>
      <w:r><w:t xml:space="preserve"> Run 2 </w:t></w:r>
      <w:r><w:t>Run\u200B 3</w:t></w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Cell 1\u2060</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Cell 2</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    """
    raw_docx = make_test_docx(body_xml)

    from docx import clean_docx_lossless

    cleaned_bytes, report = clean_docx_lossless(raw_docx)

    with zipfile.ZipFile(io.BytesIO(raw_docx)) as zo, zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zc:
        ro = ET.fromstring(zo.read("word/document.xml"))
        rc = ET.fromstring(zc.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        runs_o = len(ro.findall(".//w:r", ns))
        runs_c = len(rc.findall(".//w:r", ns))
        paras_o = len(ro.findall(".//w:p", ns))
        paras_c = len(rc.findall(".//w:p", ns))
        tables_o = len(ro.findall(".//w:tbl", ns))
        tables_c = len(rc.findall(".//w:tbl", ns))

    assert runs_o == runs_c
    assert paras_o == paras_c
    assert tables_o == tables_c


def test_idempotence():
    """Cleaner phải idempotent: clean lần 2 không sinh thêm thay đổi nào."""
    body_xml = """
    <w:p>
      <w:r><w:t>Văn bản có chứa\u200B carrier ẩn.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)

    from docx import clean_docx_lossless

    clean1, rep1 = clean_docx_lossless(raw_docx)
    clean2, rep2 = clean_docx_lossless(clean1)

    assert rep2.get("mutations_count", 0) == 0
    assert rep2.get("changed_parts", []) == []
    assert clean1 == clean2


def test_no_watermark_returns_exact_bytes():
    """Tài liệu không có watermark phải được trả về nguyên vẹn byte-for-byte."""
    body_xml = """
    <w:p>
      <w:r><w:t>Tài liệu hoàn toàn sạch sẽ.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)

    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    assert cleaned_bytes == raw_docx
    assert rep.get("mutations_count", 0) == 0


def test_soft_hyphen_and_dir_overrides_removed():
    """Soft hyphen U+00AD và directional overrides U+202E, U+200E, U+200F bị xóa."""
    body_xml = """
    <w:p>
      <w:r><w:t>Văn\u00ad bản\u202e có\u200e dấu\u200f lạ.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless, extract_canonical_visible_text

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    vis = extract_canonical_visible_text(cleaned_bytes)
    assert vis == "Văn bản có dấu lạ."
    assert "\u00ad" not in vis
    assert "\u202e" not in vis
    assert "\u200e" not in vis
    assert "\u200f" not in vis


def test_tag_characters_removed():
    """Tag characters U+E0001, U+E0020-U+E007F bị xóa sạch."""
    body_xml = """
    <w:p>
      <w:r><w:t>Ký tự tag \U000E0001\U000E0020\U000E0041ẩn.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless, extract_canonical_visible_text

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    vis = extract_canonical_visible_text(cleaned_bytes)
    assert vis == "Ký tự tag ẩn."
    assert "\U000E0001" not in vis
    assert "\U000E0020" not in vis


def test_emoji_zwj_and_variation_selector_preserved():
    """ZWJ trong chuỗi Emoji và Variation Selector trên Emoji TUYỆT ĐỐI KHÔNG BỊ XÓA."""
    # Emoji family: 👨‍👩‍👧‍👦 (U+1F468 U+200D U+1F469 U+200D U+1F467 U+200D U+1F466)
    # Heart with VS16: ❤️ (U+2764 U+FE0F)
    # Plus a real carrier ZWSP U+200B that should be removed
    body_xml = """
    <w:p>
      <w:r><w:t>Gia đình 👨\u200D👩\u200D👧\u200D👦 và trái tim ❤\uFE0F có\u200B carrier.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless, extract_canonical_visible_text

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    vis = extract_canonical_visible_text(cleaned_bytes)
    assert "👨\u200D👩\u200D👧\u200D👦" in vis
    assert "❤\uFE0F" in vis
    assert "\u200b" not in vis
    assert vis == "Gia đình 👨\u200D👩\u200D👧\u200D👦 và trái tim ❤\uFE0F có carrier."


def test_arabic_persian_zwnj_preserved():
    """ZWNJ giữa các chữ cái tiếng Ả Rập / Ba Tư (ligature breaking) phải được giữ nguyên."""
    # Persian word: میخواهم with ZWNJ: می‌خواهم (U+0645 U+06CC U+200C U+062E ...)
    body_xml = """
    <w:p>
      <w:r><w:t>Tiếng Ba Tư: می\u200Cخواهم và\u200B carrier.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless, extract_canonical_visible_text

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    vis = extract_canonical_visible_text(cleaned_bytes)
    assert "می\u200Cخواهم" in vis
    assert "\u200b" not in vis


def test_nfc_nfd_normalization_preserved():
    """Unicode normalization (NFC vs NFD) không được tự động chuyển đổi."""
    import unicodedata
    # Tiếng Việt NFC vs NFD
    text_nfc = unicodedata.normalize("NFC", "Phạm Ngọc Diệp")
    text_nfd = unicodedata.normalize("NFD", "Phạm Ngọc Diệp")
    assert text_nfc != text_nfd

    body_xml = f"""
    <w:p>
      <w:r><w:t>NFC: {text_nfc}\u200b</w:t></w:r>
      <w:r><w:t>NFD: {text_nfd}\u200b</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert f"NFC: {text_nfc}" in doc_xml
        assert f"NFD: {text_nfd}" in doc_xml


def test_footnotes_and_endnotes_cleaned():
    """Footnotes và endnotes được clean lossless và bảo toàn cấu trúc."""
    footnotes_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:footnote w:id="1">
        <w:p><w:r><w:t>Chú thích 1 có\u200B carrier.</w:t></w:r></w:p>
      </w:footnote>
    </w:footnotes>"""

    endnotes_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:endnote w:id="1">
        <w:p><w:r><w:t>Ghi chú cuối có\u2060 carrier.</w:t></w:r></w:p>
      </w:endnote>
    </w:endnotes>"""

    raw_docx = make_test_docx(
        body_xml="<w:p><w:r><w:t>Chính văn</w:t></w:r></w:p>",
        extra_parts={
            "word/footnotes.xml": footnotes_xml,
            "word/endnotes.xml": endnotes_xml,
        },
    )

    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        fn = zf.read("word/footnotes.xml").decode("utf-8")
        en = zf.read("word/endnotes.xml").decode("utf-8")
        assert "\u200b" not in fn
        assert "Chú thích 1 có carrier." in fn
        assert "\u2060" not in en
        assert "Ghi chú cuối có carrier." in en


def test_headers_and_footers_cleaned():
    """Header và Footer được clean lossless."""
    hdr_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:p><w:r><w:t>Header văn bản có\u200B watermark.</w:t></w:r></w:p>
    </w:hdr>"""

    ftr_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:p><w:r><w:t>Footer trang có\u200B watermark.</w:t></w:r></w:p>
    </w:ftr>"""

    raw_docx = make_test_docx(
        body_xml="<w:p><w:r><w:t>Body</w:t></w:r></w:p>",
        extra_parts={
            "word/header1.xml": hdr_xml,
            "word/footer1.xml": ftr_xml,
        },
    )

    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        h = zf.read("word/header1.xml").decode("utf-8")
        f = zf.read("word/footer1.xml").decode("utf-8")
        assert "\u200b" not in h
        assert "Header văn bản có watermark." in h
        assert "\u200b" not in f
        assert "Footer trang có watermark." in f


def test_complex_tables_preserved():
    """Bảng biểu với nhiều hàng cột, merge cell giữ nguyên cấu trúc."""
    body_xml = """
    <w:tbl>
      <w:tblPr><w:tblW w:w="5000" w:type="dxa"/></w:tblPr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Cột 1\u200b</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Cột 2</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Dữ liệu 1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Dữ liệu 2\u2060</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        doc = zf.read("word/document.xml").decode("utf-8")
        assert "<w:tbl>" in doc or "<w:tbl " in doc
        assert doc.count("<w:tr>") == 2 or doc.count("<w:tr ") == 2
        assert doc.count("<w:tc>") == 4 or doc.count("<w:tc ") == 4
        assert "\u200b" not in doc
        assert "\u2060" not in doc


def test_hyperlinks_and_bookmarks_preserved():
    """Hyperlinks và bookmark tags không bị xáo trộn."""
    body_xml = """
    <w:p>
      <w:bookmarkStart w:id="0" w:name="_TargetBookmark"/>
      <w:hyperlink r:id="rId99" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
        <w:r><w:t>Liên kết\u200b web</w:t></w:r>
      </w:hyperlink>
      <w:bookmarkEnd w:id="0"/>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        doc = zf.read("word/document.xml").decode("utf-8")
        assert 'w:name="_TargetBookmark"' in doc
        assert 'r:id="rId99"' in doc
        assert "\u200b" not in doc
        assert "Liên kết web" in doc


def test_field_codes_instrtext_preserved():
    """Field codes và instrText không bao giờ bị can thiệp."""
    body_xml = """
    <w:p>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText xml:space="preserve"> PAGE \u200b MERGEFORMAT </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>1</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        doc = zf.read("word/document.xml").decode("utf-8")
        # instrText retains exact contents
        assert " PAGE \u200b MERGEFORMAT " in doc


def test_core_and_app_properties_scrubbed():
    """Metadata trong core.xml được làm sạch, AppVersion và TotalTime được giữ lại."""
    core_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                       xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:creator>ChatGPT / OpenAI</dc:creator>
      <cp:lastModifiedBy>Claude Bot</cp:lastModifiedBy>
      <dc:title>Document Title Keep</dc:title>
    </cp:coreProperties>"""

    app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
      <Application>ChatGPT Generated</Application>
      <Company>OpenAI</Company>
      <AppVersion>16.0000</AppVersion>
      <TotalTime>42</TotalTime>
    </Properties>"""

    raw_docx = make_test_docx(
        body_xml="<w:p><w:r><w:t>Nội dung</w:t></w:r></w:p>",
        core_xml=core_xml,
        app_xml=app_xml,
    )
    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        c = zf.read("docProps/core.xml").decode("utf-8")
        a = zf.read("docProps/app.xml").decode("utf-8")

        assert "ChatGPT" not in c
        assert "Claude Bot" not in c
        assert "<dc:title>Document Title Keep</dc:title>" in c
        assert "<dc:creator></dc:creator>" in c or "<dc:creator/>" in c

        assert "ChatGPT" not in a
        assert "OpenAI" not in a
        assert "<AppVersion>16.0000</AppVersion>" in a
        assert "<TotalTime>42</TotalTime>" in a


def test_custom_xml_dropped_and_rels_pruned():
    """customXml/item1.xml bị drop và dangling relationship được prune chuẩn."""
    custom_xml = "<root><ai_trace>secret_watermark</ai_trace></root>"
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item1.xml"/>
      <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://google.com" TargetMode="External"/>
    </Relationships>"""

    raw_docx = make_test_docx(
        body_xml="<w:p><w:r><w:t>Text</w:t></w:r></w:p>",
        custom_xml=custom_xml,
        extra_parts={"word/_rels/document.xml.rels": rels_xml},
    )
    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        names = zf.namelist()
        assert not any(n.startswith("customXml/") for n in names)
        rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
        assert "../customXml/item1.xml" not in rels
        assert 'Target="https://google.com"' in rels


def test_embedded_media_scrubbed():
    """Embedded image trong word/media/ được scrub metadata."""
    # 1x1 PNG with tEXt chunk
    from test_ooxml_xlsx_pptx import _minimal_png_with_text
    png_bytes = _minimal_png_with_text()

    raw_docx = make_test_docx(
        body_xml="<w:p><w:r><w:t>Hình ảnh</w:t></w:r></w:p>",
        extra_parts={"word/media/image1.png": png_bytes},
    )
    from docx import clean_docx_lossless

    cleaned_bytes, rep = clean_docx_lossless(raw_docx)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes)) as zf:
        cleaned_png = zf.read("word/media/image1.png")
        assert b"tEXt" not in cleaned_png


def test_validator_detects_visible_text_divergence():
    """DocxFidelityValidator phải fail-closed nếu văn bản nhìn thấy bị sai lệch."""
    from docx.validator import DocxFidelityValidator, DocxFidelityException
    from docx.mutation_plan import DocxMutationPlan, TextCodepointMutation

    docx1 = make_test_docx("<w:p><w:r><w:t>Văn bản gốc\u200b</w:t></w:r></w:p>")
    docx2 = make_test_docx("<w:p><w:r><w:t>Văn bản khác</w:t></w:r></w:p>")

    plan = DocxMutationPlan()
    plan.text_mutations.append(
        TextCodepointMutation(
            part_name="word/document.xml",
            p_idx=0,
            r_idx=0,
            t_idx=0,
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            offset=11,
        )
    )
    validator = DocxFidelityValidator(docx1, docx2, plan)

    with pytest.raises(DocxFidelityException, match="Visible text mismatch"):
        validator.validate()


def test_validator_detects_nontarget_part_tampering():
    """DocxFidelityValidator phải raise lỗi nếu một part không nằm trong plan bị sửa đổi."""
    from docx.validator import DocxFidelityValidator, DocxFidelityException
    from docx.mutation_plan import DocxMutationPlan

    docx1 = make_test_docx(
        "<w:p><w:r><w:t>Test</w:t></w:r></w:p>",
        extra_parts={"word/theme/theme1.xml": "<theme>A</theme>"},
    )
    docx2 = make_test_docx(
        "<w:p><w:r><w:t>Test</w:t></w:r></w:p>",
        extra_parts={"word/theme/theme1.xml": "<theme>B</theme>"},
    )

    plan = DocxMutationPlan()  # theme1.xml not in plan
    validator = DocxFidelityValidator(docx1, docx2, plan)

    with pytest.raises(DocxFidelityException, match="Non-target part 'word/theme/theme1.xml' was modified"):
        validator.validate()


def test_determinism_5_runs():
    """5 lần clean liên tiếp trên cùng 1 file phải cho ra SHA256 hoàn toàn trùng khớp."""
    import hashlib

    body_xml = """
    <w:p>
      <w:r><w:t>Chương 1:\u200B Quản lý dự án.</w:t></w:r>
      <w:r><w:t> Mục tiêu:\u2060 Hoàn thành đúng hạn.</w:t></w:r>
    </w:p>
    """
    raw_docx = make_test_docx(body_xml)
    from docx import clean_docx_lossless

    hashes = []
    for _ in range(5):
        cleaned_bytes, rep = clean_docx_lossless(raw_docx)
        hashes.append(hashlib.sha256(cleaned_bytes).hexdigest())

    assert len(set(hashes)) == 1, f"Non-deterministic hashes: {hashes}"

