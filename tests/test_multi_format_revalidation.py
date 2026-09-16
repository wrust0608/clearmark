"""Tests for Phase 11: Multi-Format Revalidation and Policy Verification."""

from __future__ import annotations

import io
import zipfile
import pytest
from pathlib import Path

from service.scripts.format_policy import get_format_policy, FormatCategory
from service.scripts.container_meta import (
    clean_xlsx,
    clean_pptx,
    clean_odt,
    clean_epub,
    clean_svg,
)
from service.scripts.image_meta import strip_png, strip_jpeg, detect_format


def test_format_policy_consistency_across_all_categories():
    """Verify format policies are consistently assigned for all core categories."""
    assert get_format_policy("docx").category == FormatCategory.WORD_PROCESSING
    assert get_format_policy("docx").default_normalize_spaces is False
    assert get_format_policy("docx").allow_llm_rewrite is False
    assert get_format_policy("docx").structural_invariants_required is True

    assert get_format_policy("xlsx").category == FormatCategory.SPREADSHEET
    assert get_format_policy("pptx").category == FormatCategory.PRESENTATION
    assert get_format_policy("odt").category == FormatCategory.ODF_DOCUMENT
    assert get_format_policy("pdf").category == FormatCategory.PDF_DOCUMENT
    assert get_format_policy("png").category == FormatCategory.RASTER_IMAGE


def test_revalidate_xlsx():
    """Verify XLSX cleaning cleans metadata and handles sharedStrings without regression."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/sharedStrings.xml", "<sst><si><t>Bảng tính\u200B1</t></si></sst>")
        zf.writestr("docProps/core.xml", "<cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org/package/2006/metadata/core-properties' xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:creator>Author</dc:creator></cp:coreProperties>")

    cleaned_bytes, actions = clean_xlsx(buf.getvalue(), also_layer_a_text=True)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as zf:
        ss_content = zf.read("xl/sharedStrings.xml").decode("utf-8")
        assert "\u200B" not in ss_content
        assert "Bảng tính" in ss_content
    assert any("sharedStrings.xml" in a or "layer A" in a for a in actions)


def test_revalidate_pptx():
    """Verify PPTX cleaning handles presentation slides properly."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("ppt/slides/slide1.xml", "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><a:p><a:r><a:t>Slide\u200BTitle</a:t></a:r></a:p></p:sld>")
        zf.writestr("docProps/core.xml", "<cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org/package/2006/metadata/core-properties' xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:creator>Presenter</dc:creator></cp:coreProperties>")

    cleaned_bytes, actions = clean_pptx(buf.getvalue(), also_layer_a_text=True)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as zf:
        slide_content = zf.read("ppt/slides/slide1.xml").decode("utf-8")
        assert "\u200B" not in slide_content
        assert "Slide" in slide_content


def test_revalidate_odt():
    """Verify ODT cleaning scrubs content.xml and meta.xml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", "<office:document-content xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0' xmlns:text='urn:oasis:names:tc:opendocument:xmlns:text:1.0'><office:body><office:text><text:p>ODF\u200BDocument</text:p></office:text></office:body></office:document-content>")
        zf.writestr("meta.xml", "<office:document-meta xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0' xmlns:meta='urn:oasis:names:tc:opendocument:xmlns:meta:1.0'><office:meta><meta:initial-creator>User</meta:initial-creator></office:meta></office:document-meta>")

    cleaned_bytes, actions = clean_odt(buf.getvalue(), also_layer_a_text=True)
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as zf:
        content = zf.read("content.xml").decode("utf-8")
        assert "\u200B" not in content
        assert "ODF" in content


def test_revalidate_png_and_jpeg():
    """Verify PNG and JPEG metadata stripping functions normally."""
    # 1x1 transparent PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    fmt = detect_format(png_bytes)
    assert fmt == "png"
    cleaned_png, actions = strip_png(png_bytes)
    assert cleaned_png.startswith(b"\x89PNG")

    # 1x1 minimal JPEG
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00"
        b"\xff\xd9"
    )
    fmt = detect_format(jpeg_bytes)
    assert fmt == "jpeg"
    cleaned_jpeg, actions = strip_jpeg(jpeg_bytes)
    assert cleaned_jpeg.startswith(b"\xff\xd8")
