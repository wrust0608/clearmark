"""Tests for Phase 9: API and CLI Integration."""

from __future__ import annotations

import base64
import io
import time
import zipfile
import pytest
from pathlib import Path

import server
from service.scripts.container_meta import clean_container
from service.scripts.docx import extract_canonical_visible_text

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _build_test_docx() -> bytes:
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Nhiệm vụ\u00A0quản lý\u200Btài liệu</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def test_api_clean_file_docx_enforces_format_policy():
    """Verify /clean/file endpoint enforces format policy (no LLM rewrite, normalize_spaces=False for DOCX)."""
    raw_docx = _build_test_docx()
    # Client requests normalize_spaces=True and statistical_rewrite=True
    options = {
        "normalize_spaces": True,
        "statistical_rewrite": True,
        "also_layer_a_text": True,
    }

    t0 = time.perf_counter()
    resp = server._clean_payload(raw_docx, "test_document.docx", options)
    elapsed = time.perf_counter() - t0

    assert resp["ok"] is True
    assert resp["kind"] == "container"
    cleaned_bytes = base64.b64decode(resp["cleaned"])

    # Processing a simple DOCX file must complete well under 200ms
    assert elapsed < 0.200

    # Non-breaking space U+00A0 MUST NOT be collapsed to regular space
    text_before = extract_canonical_visible_text(raw_docx)
    text_after = extract_canonical_visible_text(cleaned_bytes)

    assert "\u00A0" in text_after  # U+00A0 preserved
    assert "\u200B" not in text_after  # U+200B carrier stripped
    assert text_after == "Nhiệm vụ\u00A0quản lýtài liệu"


def test_clean_container_docx_file_interface(tmp_path: Path):
    """Verify clean_container properly handles file-based DOCX transformation."""
    raw_docx = _build_test_docx()
    src_file = tmp_path / "input.docx"
    dest_file = tmp_path / "output.docx"
    src_file.write_bytes(raw_docx)

    # Invoke clean_container
    result = clean_container(src_file, dest_file)

    assert dest_file.exists()
    assert result["format"] == "docx"
    assert "actions" in result

    cleaned_bytes = dest_file.read_bytes()
    text_after = extract_canonical_visible_text(cleaned_bytes)
    assert "\u200B" not in text_after
    assert "\u00A0" in text_after
