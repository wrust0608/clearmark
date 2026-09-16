"""tests/test_golden_revalidation_and_negative_witnesses.py

Regression test suite for Section 0, 2, 4, 6, 7 of the Master Revalidation Task:
- Locks Golden Original (c05ca5c1...) with 288 runs, 5 page breaks, 19 pages
- Verifies that Validator correctly FAILS Negative Witnesses 02 and 03
- Asserts page breaks (<w:br w:type="page"/>) and run counts are strictly invariant
"""

import hashlib
import io
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
import pytest

from docx.cleaner import clean_docx_lossless
from docx.validator import DocxFidelityValidator, DocxFidelityException
from docx.mutation_plan import DocxMutationPlan
from docx.package import DocxPackage

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
WITNESS_A_PATH = ROOT / "02_BAD_OUTPUT_RUN_EXPLOSION.docx"
WITNESS_B_PATH = ROOT / "03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION.docx"

EXPECTED_GOLDEN_SHA = "c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d"
EXPECTED_GOLDEN_SIZE = 49959


def test_golden_original_lock_and_metrics():
    """Verify Golden Original exists and matches exact cryptographic hash and structural metrics."""
    assert GOLDEN_PATH.exists(), f"Golden original file not found at {GOLDEN_PATH}"
    data = GOLDEN_PATH.read_bytes()

    assert len(data) == EXPECTED_GOLDEN_SIZE, f"Golden size mismatch: {len(data)} != {EXPECTED_GOLDEN_SIZE}"
    sha = hashlib.sha256(data).hexdigest()
    assert sha == EXPECTED_GOLDEN_SHA, f"Golden SHA256 mismatch: {sha} != {EXPECTED_GOLDEN_SHA}"

    pkg = DocxPackage(data)
    assert len(pkg.member_order) == 15, f"Expected 15 ZIP members, got {len(pkg.member_order)}"

    doc_xml = pkg.get_member("word/document.xml")
    assert doc_xml is not None
    root = ET.fromstring(doc_xml)

    paras = len(root.findall(".//w:p", NS))
    runs = len(root.findall(".//w:r", NS))
    tables = len(root.findall(".//w:tbl", NS))
    rows = len(root.findall(".//w:tr", NS))
    cells = len(root.findall(".//w:tc", NS))
    brs = root.findall(".//w:br", NS)
    page_breaks = sum(1 for b in brs if b.get(f"{{{W_NS}}}type") == "page")
    sections = len(root.findall(".//w:sectPr", NS))

    assert paras == 204, f"Expected 204 paragraphs, got {paras}"
    assert runs == 288, f"Expected 288 runs, got {runs}"
    assert tables == 1, f"Expected 1 table, got {tables}"
    assert rows == 7, f"Expected 7 rows, got {rows}"
    assert cells == 49, f"Expected 49 cells, got {cells}"
    assert page_breaks == 5, f"Expected 5 manual page breaks, got {page_breaks}"
    assert sections == 1, f"Expected 1 section, got {sections}"


def test_validator_fails_candidate_a_run_explosion():
    """Verify that Candidate A (02_BAD_OUTPUT_RUN_EXPLOSION) is rejected by validator with multiple violations."""
    assert WITNESS_A_PATH.exists()
    golden_bytes = GOLDEN_PATH.read_bytes()
    bad_bytes = WITNESS_A_PATH.read_bytes()

    # 1. Standard plan check fails because non-target parts changed without plan
    val = DocxFidelityValidator(golden_bytes, bad_bytes, DocxMutationPlan())
    with pytest.raises(DocxFidelityException):
        val.validate()

    # 2. Even if package was initialized, structure validation detects run explosion & page break loss
    val.clean_pkg = DocxPackage(bad_bytes)
    with pytest.raises(DocxFidelityException) as exc_struct:
        val._validate_structure()
    err_msg = str(exc_struct.value)
    # Must catch run count explosion (288 -> 6467) or page break change (5 -> 4)
    assert ("Run count changed! Before: 288, After: 6467" in err_msg or
            "Manual page break count changed! Before: 5, After: 4" in err_msg)

    # 3. Visible text validation also fails
    with pytest.raises(DocxFidelityException):
        val._validate_visible_text()


def test_validator_fails_candidate_b_layout_regression():
    """Verify that Candidate B (03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION) is rejected by validator."""
    assert WITNESS_B_PATH.exists()
    golden_bytes = GOLDEN_PATH.read_bytes()
    bad_bytes = WITNESS_B_PATH.read_bytes()

    val = DocxFidelityValidator(golden_bytes, bad_bytes, DocxMutationPlan())
    with pytest.raises(DocxFidelityException):
        val.validate()

    val.clean_pkg = DocxPackage(bad_bytes)
    with pytest.raises(DocxFidelityException) as exc_struct:
        val._validate_structure()
    err_msg = str(exc_struct.value)
    assert ("Run count changed! Before: 288, After: 6467" in err_msg or
            "Manual page break count changed! Before: 5, After: 4" in err_msg)


def test_page_break_run_without_text_preserved():
    """Regression test: <w:r><w:br w:type='page'/></w:r> must NEVER be removed or altered."""
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{W_NS}">
      <w:body>
        <w:p>
          <w:r><w:t>Trang 1: Đoạn văn trước ngắt trang\u200B</w:t></w:r>
        </w:p>
        <w:p>
          <w:r>
            <w:br w:type="page"/>
          </w:r>
        </w:p>
        <w:p>
          <w:r><w:t>Trang 2: Đoạn văn sau ngắt trang</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml.encode("utf-8"))
        z.writestr("[Content_Types].xml", b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("_rels/.rels", b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr("docProps/core.xml", b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')

    raw = buf.getvalue()
    clean, rep = clean_docx_lossless(raw)
    assert rep["fidelity_guaranteed"] is True

    pkg = DocxPackage(clean)
    doc_tree = ET.fromstring(pkg.get_member("word/document.xml"))
    brs = [b for b in doc_tree.findall(".//w:br", NS) if b.get(f"{{{W_NS}}}type") == "page"]
    assert len(brs) == 1, "Manual page break was deleted or altered!"
