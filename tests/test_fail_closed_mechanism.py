"""Tests for Phase 8: Fail-Closed Behavior and Safe Rollback Mechanism."""

from __future__ import annotations

import io
import zipfile
import pytest

from service.scripts.docx import (
    clean_docx_lossless,
    DocxFidelityException,
)
import service.scripts.container_meta as container_meta

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_docx_with_carrier() -> bytes:
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Văn bản\u200Bchuẩn tắc</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def test_fail_closed_rolls_back_to_original_bytes(monkeypatch: pytest.MonkeyPatch):
    """Verify that if fidelity validation fails, cleaner automatically rolls back to original bytes."""
    data = _make_docx_with_carrier()

    # Simulate a bug in patcher that would corrupt text ("Văn bản" -> "Văn")
    from service.scripts.docx.patcher import DocxPatcher
    orig_apply = DocxPatcher.apply

    def faulty_apply(self):
        # Corrupt the text
        bad_doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Vănchuẩn tắc</w:t></w:r></w:p>
  </w:body>
</w:document>"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", bad_doc_xml)
            zf.writestr("[Content_Types].xml", "<Types/>")
        return buf.getvalue()

    monkeypatch.setattr(DocxPatcher, "apply", faulty_apply)

    # Call cleaner with default fail-closed behavior
    result_bytes, report = clean_docx_lossless(data)

    # 1. Output must be 100% byte-for-byte identical to input
    assert result_bytes == data
    # 2. Report must flag failure and rollback
    assert report["changed"] is False
    assert report["fidelity_guaranteed"] is False
    assert "rolled back to original" in report["actions"][0]
    assert "error" in report


def test_raise_on_violation_option(monkeypatch: pytest.MonkeyPatch):
    """Verify that callers requesting strict exceptions receive DocxFidelityException."""
    data = _make_docx_with_carrier()

    from service.scripts.docx.patcher import DocxPatcher

    def faulty_apply(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<w:document><w:body/></w:document>")
            zf.writestr("[Content_Types].xml", "<Types/>")
        return buf.getvalue()

    monkeypatch.setattr(DocxPatcher, "apply", faulty_apply)

    with pytest.raises(DocxFidelityException):
        clean_docx_lossless(data, options={"raise_on_violation": True})


def test_container_meta_clean_docx_fail_closed_integration(monkeypatch: pytest.MonkeyPatch):
    """Verify that container_meta.clean_docx wrapper safely returns original bytes on failure."""
    data = _make_docx_with_carrier()

    import docx.patcher

    def faulty_apply(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<w:document><w:body/></w:document>")
            zf.writestr("[Content_Types].xml", "<Types/>")
        return buf.getvalue()

    monkeypatch.setattr(docx.patcher.DocxPatcher, "apply", faulty_apply)

    cleaned_bytes, actions = container_meta.clean_docx(data)
    assert cleaned_bytes == data
    assert any("rolled back to original" in a for a in actions)
