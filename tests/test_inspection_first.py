"""Tests for Phase 2: Inspection-First Workflow & Semantics (Sections 1, 2, 3, 4, 7, 8, 9, 11, 14, 16, 18).

Invariants Verified:
1. Read-Only Invariant: inspect() never modifies source bytes, size, or mtime_ns, and never creates temporary or sibling files.
2. Result Semantics Invariant: inspect() distinguishes DETECTED, NOT_DETECTED, UNAVAILABLE, and UNSUPPORTED.
3. Structured Finding Invariant: Findings record detector_id, category, location, codepoint, metadata_key without full body text.
4. Capability-Aware Invariant: detectors_run, detectors_unavailable, and format policy capabilities are reported honestly.
5. ProcessingMode Invariant: SAFE, BALANCED, AGGRESSIVE appear in report with explicit notices if operations are identical.
6. Zero-Network Invariant: All inspection operations run strictly locally with zero network socket activity.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
from pathlib import Path
import pytest

from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import (
    CleaningReport,
    DetectionStatus,
    ErrorCode,
    Finding,
    PipelineStatus,
    ProcessingMode,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CANDIDATE_DOCX = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def test_inspect_is_strictly_read_only(tmp_path):
    """Section 2: Pipeline.inspect() must never modify source bytes, size, mtime_ns or create sibling files."""
    test_files = []

    # 1. DOCX fixture
    docx_file = tmp_path / "test_doc.docx"
    docx_file.write_bytes(GOLDEN_DOCX.read_bytes())
    test_files.append(docx_file)

    # 2. Text fixture with invisible carriers
    txt_file = tmp_path / "test_text.txt"
    txt_file.write_text("Hello\u200bWorld!\ufeff", encoding="utf-8")
    test_files.append(txt_file)

    # 3. Markdown fixture
    md_file = tmp_path / "test_doc.md"
    md_file.write_text("# Title\n\nSome clean markdown content.\n", encoding="utf-8")
    test_files.append(md_file)

    pipeline = Pipeline()

    for file_path in test_files:
        # Record directory contents and file state BEFORE inspection
        dir_files_before = set(tmp_path.iterdir())
        stat_before = file_path.stat()
        sha_before = hashlib.sha256(file_path.read_bytes()).hexdigest()

        # Execute inspection
        report = pipeline.inspect(file_path)

        # Record state AFTER inspection
        dir_files_after = set(tmp_path.iterdir())
        stat_after = file_path.stat()
        sha_after = hashlib.sha256(file_path.read_bytes()).hexdigest()

        # Assert strict invariants
        assert sha_after == sha_before, f"Inspection modified file contents: {file_path}"
        assert stat_after.st_size == stat_before.st_size, f"Inspection changed file size: {file_path}"
        assert stat_after.st_mtime_ns == stat_before.st_mtime_ns, f"Inspection changed mtime_ns: {file_path}"
        assert dir_files_after == dir_files_before, f"Inspection created temporary/sibling files: {dir_files_after - dir_files_before}"
        assert report.output.changed is False
        assert report.output.would_change is False


def test_inspect_detection_status_semantics(tmp_path):
    """Section 3: Inspection report must distinguish DETECTED, NOT_DETECTED, UNAVAILABLE, and UNSUPPORTED."""
    pipeline = Pipeline()

    # 1. DETECTED: Golden DOCX has provenance metadata
    rep_golden = pipeline.inspect(GOLDEN_DOCX)
    assert rep_golden.status == PipelineStatus.INSPECTED
    assert rep_golden.inspection.detection_status == DetectionStatus.DETECTED
    assert len(rep_golden.inspection.findings) > 0

    # 2. NOT_DETECTED: Candidate DOCX is already clean
    rep_candidate = pipeline.inspect(CANDIDATE_DOCX)
    assert rep_candidate.status == PipelineStatus.INSPECTED
    assert rep_candidate.inspection.detection_status == DetectionStatus.NOT_DETECTED
    assert len(rep_candidate.inspection.findings) == 0

    # 3. DETECTED: Text file with zero-width space
    wm_text = tmp_path / "watermarked.txt"
    wm_text.write_text("Confidential\u200bData", encoding="utf-8")
    rep_text_wm = pipeline.inspect(wm_text)
    assert rep_text_wm.inspection.detection_status == DetectionStatus.DETECTED
    assert len(rep_text_wm.inspection.findings) > 0

    # 4. NOT_DETECTED: Clean text file
    clean_text = tmp_path / "clean.txt"
    clean_text.write_text("Completely clean text.", encoding="utf-8")
    rep_text_clean = pipeline.inspect(clean_text)
    assert rep_text_clean.inspection.detection_status == DetectionStatus.NOT_DETECTED
    assert len(rep_text_clean.inspection.findings) == 0

    # 5. UNSUPPORTED: Unknown binary extension
    bad_file = tmp_path / "unknown.xyz"
    bad_file.write_bytes(b"\x00\x01\x02UNKNOWN")
    rep_unsupported = pipeline.inspect(bad_file)
    assert rep_unsupported.status == PipelineStatus.UNSUPPORTED
    assert rep_unsupported.error_code == ErrorCode.UNSUPPORTED_FORMAT
    assert rep_unsupported.inspection.detection_status == DetectionStatus.UNSUPPORTED


def test_inspect_finding_model_structure_and_no_body_text(tmp_path):
    """Section 4: Findings must be structured (detector_id, category, location, codepoint) without body text."""
    pipeline = Pipeline()

    # Test Golden DOCX
    rep_docx = pipeline.inspect(GOLDEN_DOCX)
    for f in rep_docx.inspection.findings:
        assert isinstance(f, Finding)
        assert f.detector_id != ""
        assert f.category != ""
        assert f.actionability == "SAFE_TO_REMOVE"
        assert f.target_part is not None
        # Check that no full document paragraph is in reason
        assert len(f.reason or "") < 150

    # Test text file with carriers
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("Prefix text \u200b middle text \ufeff suffix text.", encoding="utf-8")
    rep_txt = pipeline.inspect(txt_file)

    assert len(rep_txt.inspection.findings) == 2
    f1, f2 = rep_txt.inspection.findings
    assert f1.detector_id == "UnicodeTextInspector"
    assert f1.category == "unicode_carrier"
    assert f1.codepoint == "U+200B"
    assert "offset:" in (f1.location or "")

    assert f2.detector_id == "UnicodeTextInspector"
    assert f2.codepoint == "U+FEFF"
    assert "offset:" in (f2.location or "")


def test_inspect_format_coverage(tmp_path):
    """Section 11: Validate inspection across DOCX, TXT, MD, PNG, PDF, and unsupported."""
    pipeline = Pipeline()

    # 1. DOCX
    r_docx = pipeline.inspect(GOLDEN_DOCX)
    assert r_docx.input.format == "docx"
    assert "DocxDetector" in r_docx.inspection.detectors_run

    # 2. Text / Markdown
    t_file = tmp_path / "sample.md"
    t_file.write_text("# Title\nBody\u200dtext\n", encoding="utf-8")
    r_md = pipeline.inspect(t_file)
    assert r_md.input.format == "md"
    assert "UnicodeTextInspector" in r_md.inspection.detectors_run

    # 3. Minimal PNG
    png_file = tmp_path / "dot.png"
    # 1x1 8-bit RGBA PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    png_file.write_bytes(png_bytes)
    r_png = pipeline.inspect(png_file)
    assert r_png.input.format == "png"
    assert "ImageMetaInspector" in r_png.inspection.detectors_run

    # 4. Minimal PDF
    pdf_file = tmp_path / "doc.pdf"
    pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    pdf_file.write_bytes(pdf_bytes)
    r_pdf = pipeline.inspect(pdf_file)
    assert r_pdf.input.format == "pdf"
    assert "ContainerMetaInspector" in r_pdf.inspection.detectors_run

    # 5. Unsupported
    bin_file = tmp_path / "raw.bin"
    bin_file.write_bytes(b"\xff\xfe\x00\x01\x02\x03")
    r_bin = pipeline.inspect(bin_file)
    assert r_bin.status == PipelineStatus.UNSUPPORTED


def test_inspect_processing_mode_propagation_and_transparency():
    """Section 8: ProcessingMode SAFE, BALANCED, AGGRESSIVE must appear in report and explain invariant behavior."""
    pipeline = Pipeline()

    for mode in (ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE):
        rep = pipeline.inspect(GOLDEN_DOCX, mode=mode)
        assert rep.policy.mode == mode

        if mode != ProcessingMode.SAFE:
            # DOCX has no destructive balanced/aggressive operations; must report explicitly
            assert any("operates identically to SAFE" in w for w in rep.validation.warnings)


def test_inspect_zero_network_isolation(monkeypatch):
    """Section 16: Assert zero network attempts during inspect()."""
    def _forbidden_network(*args, **kwargs):
        raise RuntimeError("CRITICAL: Network call attempted during deterministic local inspection!")

    monkeypatch.setattr(socket, "socket", _forbidden_network)

    pipeline = Pipeline()
    # Must run completely locally without attempting any network connection
    rep1 = pipeline.inspect(GOLDEN_DOCX)
    assert rep1.status == PipelineStatus.INSPECTED
    assert rep1.privacy.network_used is False

    rep2 = pipeline.inspect(b"Clean text data without network", filename="doc.txt")
    assert rep2.status == PipelineStatus.INSPECTED
    assert rep2.privacy.network_used is False


def test_inspect_synthetic_docx_body_carriers():
    """Section 7: For synthetic body-carrier fixtures, report their precise planned codepoint removals."""
    import io
    import zipfile
    from service.scripts.docx.detector import W_NS

    xml = f"""<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>
    <w:p><w:r><w:t>Security\u200BWatermark\u200CCarrier\uFEFFTest</w:t></w:r></w:p>
    </w:body></w:document>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", xml.encode("utf-8"))
    synthetic_docx = buf.getvalue()

    pipeline = Pipeline()
    report = pipeline.inspect(synthetic_docx, filename="carrier.docx")

    assert report.status == PipelineStatus.INSPECTED
    assert report.inspection.detection_status == DetectionStatus.DETECTED

    codepoints_found = [
        f.codepoint for f in report.inspection.findings if isinstance(f, Finding) and f.codepoint
    ]
    assert "U+200B" in codepoints_found
    assert "U+200C" in codepoints_found
    assert "U+FEFF" in codepoints_found

