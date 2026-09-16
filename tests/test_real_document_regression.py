"""tests/test_real_document_regression.py

Automated Real-Document Regression Test.
Verifies the True Golden Original ('01_GOLDEN_ORIGINAL_UNTOUCHED.docx')
or complex synthetic counterparts against the 5-layer fidelity invariants.
"""

import hashlib
import io
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

from docx.cleaner import clean_docx_lossless
from docx.package import DocxPackage
from docx.visible_text import extract_canonical_visible_text
from tools.verify_document_fidelity import analyze_docx_fidelity

GOLDEN_DOCX = Path(__file__).resolve().parent.parent / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
REAL_DOCX = GOLDEN_DOCX
REGRESS_DOCX = Path(__file__).resolve().parent.parent / "02_BAD_OUTPUT_RUN_EXPLOSION.docx"


def _generate_synthetic_complex_document() -> bytes:
    """Fallback synthetic document with Vietnamese content, tables, and watermarks."""
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{W_NS}">
      <w:body>
        <w:p>
          <w:r><w:t>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</w:t></w:r>
        </w:p>
        <w:p>
          <w:r><w:t>Độc lập - Tự do - Hạnh phúc</w:t></w:r>
        </w:p>
        <w:p>
          <w:r><w:t>BÁO CÁO KẾT QUẢ CÔNG TÁC QUẢN LÝ</w:t></w:r>
        </w:p>
        <w:p>
          <w:r><w:t>1. Công tác </w:t></w:r>
          <w:r><w:t>Quản\u200B</w:t></w:r>
          <w:r><w:t> lý chất lượng công trình:</w:t></w:r>
        </w:p>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>STT</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Nội dung</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Đánh giá</w:t></w:r></w:p></w:tc>
          </w:tr>
          <w:tr>
            <w:tc><w:p><w:r><w:t>01</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Hồ sơ thiết kế kỹ thuật</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Đạt tiêu chuẩn\u200C xây dựng</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
        <w:p>
          <w:r><w:t>Kết luận: Đảm bảo tuyệt đối </w:t></w:r>
          <w:r><w:t>an toàn\u200D trong thi công.</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc_xml.encode("utf-8"))
        z.writestr("[Content_Types].xml", b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("_rels/.rels", b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr("docProps/core.xml", b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')
    return buf.getvalue()


def test_real_or_complex_document_regression():
    """Verify fidelity on the benchmark document if available, or on a synthetic complex fixture."""
    if REAL_DOCX.exists():
        raw_bytes = REAL_DOCX.read_bytes()
        regress_bytes = REGRESS_DOCX.read_bytes() if REGRESS_DOCX.exists() else None
    else:
        raw_bytes = _generate_synthetic_complex_document()
        regress_bytes = None

    clean_bytes, report = clean_docx_lossless(raw_bytes)

    # 1. Cleaner report must guarantee fidelity
    assert report["fidelity_guaranteed"] is True

    # 2. Detailed fidelity analysis
    analysis = analyze_docx_fidelity(raw_bytes, clean_bytes, regress_bytes)
    assert analysis["fidelity_guaranteed"] is True
    assert analysis["visible_text_identical"] is True

    # 3. Structural invariant: delta = 0
    deltas = analysis["structural_deltas"]
    assert deltas["paragraphs"] == 0
    assert deltas["runs"] == 0
    assert deltas["tables"] == 0

    # 4. Spot check Vietnamese phrases
    for sc in analysis["spot_checks"]:
        if sc["in_original"]:
            assert sc["in_clean"] is True, f"Phrase '{sc['phrase']}' missing from cleaned doc"
            assert sc["glued_in_clean"] is False, f"Phrase '{sc['phrase']}' was glued in cleaned doc!"

    # 5. Zip integrity
    with zipfile.ZipFile(io.BytesIO(clean_bytes)) as z:
        assert z.testzip() is None


def test_determinism_on_real_or_complex():
    """Ensure cleaning is 100% deterministic (identical bytes & SHA256 across runs)."""
    raw_bytes = REAL_DOCX.read_bytes() if REAL_DOCX.exists() else _generate_synthetic_complex_document()

    clean1, _ = clean_docx_lossless(raw_bytes)
    clean2, _ = clean_docx_lossless(raw_bytes)
    clean3, _ = clean_docx_lossless(raw_bytes)

    sha1 = hashlib.sha256(clean1).hexdigest()
    sha2 = hashlib.sha256(clean2).hexdigest()
    sha3 = hashlib.sha256(clean3).hexdigest()

    assert sha1 == sha2 == sha3
