"""Tests for Phase 7: Automated Fidelity Validation Framework."""

from __future__ import annotations

import io
import zipfile
import pytest

from service.scripts.docx import (
    DocxFidelityException,
    DocxFidelityValidator,
    DocxMutationPlan,
    DocxPackage,
    TextCodepointMutation,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_sample_docx(doc_xml: str, extra_parts: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")
        if extra_parts:
            for name, content in extra_parts.items():
                zf.writestr(name, content)
    return buf.getvalue()


def test_validation_passes_on_faithful_clean():
    """Verify that a compliant candidate passes all 5 layers with comprehensive report."""
    orig_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Xin chào\u200Bthế giới</w:t></w:r></w:p>
  </w:body>
</w:document>"""

    clean_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Xin chàothế giới</w:t></w:r></w:p>
  </w:body>
</w:document>"""

    orig_data = _make_sample_docx(orig_xml, {"word/fontTable.xml": "<fonts/>"})
    clean_data = _make_sample_docx(clean_xml, {"word/fontTable.xml": "<fonts/>"})

    plan = DocxMutationPlan(
        text_mutations=[
            TextCodepointMutation(
                part_name="word/document.xml",
                p_idx=0,
                r_idx=0,
                t_idx=0,
                codepoint=0x200B,
                char_name="ZERO WIDTH SPACE",
                offset=8,
            )
        ]
    )

    validator = DocxFidelityValidator(orig_data, clean_data, plan)
    report = validator.validate()

    assert report["package_valid"] is True
    assert report["non_target_parts_verified"] is True
    assert report["visible_text_exact_match"] is True
    assert report["structural_invariants_passed"] is True
    assert report["paragraph_count"] == 1
    assert report["run_count"] == 1
    assert report["removed_carrier_chars"] == 1


def test_validation_fails_on_visible_text_divergence():
    """Verify validator catches semantic drift or missing text."""
    orig_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Quản lý tài liệu</w:t></w:r></w:p>
  </w:body>
</w:document>"""

    # Candidate incorrectly changed "Quản lý" to "Quảnlý" (loss of space)
    bad_clean_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Quảnlý tài liệu</w:t></w:r></w:p>
  </w:body>
</w:document>"""

    orig_data = _make_sample_docx(orig_xml)
    bad_clean_data = _make_sample_docx(bad_clean_xml)

    # Plan targets word/document.xml for carrier removal
    plan = DocxMutationPlan(
        text_mutations=[
            TextCodepointMutation(
                part_name="word/document.xml",
                p_idx=0,
                r_idx=0,
                t_idx=0,
                codepoint=0x200B,
                char_name="ZERO WIDTH SPACE",
                offset=0,
            )
        ]
    )

    validator = DocxFidelityValidator(orig_data, bad_clean_data, plan)
    with pytest.raises(DocxFidelityException) as excinfo:
        validator.validate()
    assert "Visible text mismatch" in str(excinfo.value)


def test_validation_fails_on_structural_paragraph_change():
    """Verify validator catches merged or deleted paragraphs."""
    orig_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Đoạn 1</w:t></w:r></w:p>
    <w:p><w:r><w:t>Đoạn 2</w:t></w:r></w:p>
  </w:body>
</w:document>"""

    # Merged paragraphs into 1
    bad_clean_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:r><w:t>Đoạn 1\nĐoạn 2</w:t></w:r></w:p>
  </w:body>
</w:document>"""

    orig_data = _make_sample_docx(orig_xml)
    bad_clean_data = _make_sample_docx(bad_clean_xml)

    plan = DocxMutationPlan(
        text_mutations=[
            TextCodepointMutation(
                part_name="word/document.xml",
                p_idx=0,
                r_idx=0,
                t_idx=0,
                codepoint=0x200B,
                char_name="ZERO WIDTH SPACE",
                offset=0,
            )
        ]
    )
    validator = DocxFidelityValidator(orig_data, bad_clean_data, plan)
    with pytest.raises(DocxFidelityException) as excinfo:
        validator.validate()
    assert "Paragraph count changed" in str(excinfo.value)


def test_validation_fails_on_non_target_hash_mutation():
    """Verify validator catches unexpected modifications to untargeted files."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body><w:p><w:r><w:t>Text</w:t></w:r></w:p></w:body>
</w:document>"""

    orig_data = _make_sample_docx(doc_xml, {"word/fontTable.xml": "<fonts v='1'/>"})
    # Attacker or faulty routine modified fontTable.xml
    bad_clean_data = _make_sample_docx(doc_xml, {"word/fontTable.xml": "<fonts v='2'/>"})

    plan = DocxMutationPlan()
    validator = DocxFidelityValidator(orig_data, bad_clean_data, plan)
    with pytest.raises(DocxFidelityException) as excinfo:
        validator.validate()
    assert "Non-target part 'word/fontTable.xml' was modified" in str(excinfo.value)


def test_validation_fails_on_corrupted_xml():
    """Verify validator catches unclosed XML tags."""
    orig_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body><w:p><w:r><w:t>Text</w:t></w:r></w:p></w:body>
</w:document>"""

    corrupted_xml = "<w:document><w:body><w:p><w:r><w:t>Unclosed"

    orig_data = _make_sample_docx(orig_xml)
    bad_clean_data = _make_sample_docx(corrupted_xml)

    plan = DocxMutationPlan()
    validator = DocxFidelityValidator(orig_data, bad_clean_data, plan)
    with pytest.raises(DocxFidelityException) as excinfo:
        validator.validate()
    assert "Cleaning corrupted XML part" in str(excinfo.value)


def test_validation_fails_on_corrupted_zip():
    """Verify validator catches invalid ZIP archives."""
    orig_data = _make_sample_docx(f"<w:document xmlns:w='{W_NS}'><w:body/></w:document>")
    bad_data = b"NOT A VALID ZIP FILE HEADER"

    plan = DocxMutationPlan()
    validator = DocxFidelityValidator(orig_data, bad_data, plan)
    with pytest.raises(DocxFidelityException) as excinfo:
        validator.validate()
    assert "not a valid ZIP package" in str(excinfo.value)
