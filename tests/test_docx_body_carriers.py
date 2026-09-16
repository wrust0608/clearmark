"""Phase 6: True DOCX Body-Carrier Fixture Corpus & Contextual Preservation Tests.

Verifies:
1. Manifest integrity & cryptographic provenance for all 12 DOCX fixtures.
2. Detection and removal of real invisible body carriers (ZWSP, bidi controls, Unicode tags, multi-part carriers).
3. Exact contextual preservation of legitimate Unicode counterexamples (emoji ZWJ, Arabic joiners, Devanagari conjuncts, NBSP, NFC/NFD).
4. Structural invariants before and after cleaning:
   - run_count_before == run_count_after (no run splitting or reconstruction)
   - paragraph_count, table_count, row_count, cell_count, page_break_count, tab_count invariants
   - non-text run children (<w:br/>, <w:tab/>, <w:br w:type="page"/>) preservation
   - xml:space="preserve" preservation
5. Package fidelity: non-target ZIP members remain byte-for-byte identical.
6. Mutation plan truthfulness: planned mutations match actual OOXML changes.
7. Zero false positives and zero false negatives across the corpus.
8. Pipeline inspection, dry-run parity, CLI integration, report privacy, zero network, and idempotence.
9. Golden v2.0 regression & frozen core diff invariance.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "docx_body_carriers"
MANIFEST_PATH = FIXTURES_DIR / "MANIFEST.json"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT))

from service.scripts.docx import (
    DocxDetector,
    DocxFidelityValidator,
    DocxMutationPlan,
    DocxPackage,
    clean_docx_lossless,
)
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import DetectionStatus, ProcessingMode

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

GOLDEN_ORIGINAL_SHA = "c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d"
CANDIDATE_OUTPUT_SHA = "7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get_structure_counts(docx_bytes: bytes) -> dict[str, int]:
    """Extract structural element counts from word/document.xml in docx_bytes."""
    with zipfile.ZipFile(io_bytes := io_from_bytes(docx_bytes)) as zf:
        doc_xml = zf.read("word/document.xml")
    root = ET.fromstring(doc_xml)
    return {
        "paragraph_count": len(root.findall(".//w:p", NS)),
        "run_count": len(root.findall(".//w:r", NS)),
        "table_count": len(root.findall(".//w:tbl", NS)),
        "table_row_count": len(root.findall(".//w:tr", NS)),
        "table_cell_count": len(root.findall(".//w:tc", NS)),
        "manual_page_break_count": len(root.findall(".//w:br[@w:type='page']", NS)),
        "tab_count": len(root.findall(".//w:tab", NS)),
        "bookmark_count": len(root.findall(".//w:bookmarkStart", NS)),
        "hyperlink_count": len(root.findall(".//w:hyperlink", NS)),
    }


def io_from_bytes(data: bytes):
    import io
    return io.BytesIO(data)


def _get_zip_members_payload(docx_bytes: bytes) -> dict[str, bytes]:
    """Extract uncompressed bytes for every member in docx_bytes."""
    with zipfile.ZipFile(io_from_bytes(docx_bytes)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _read_manifest() -> dict:
    assert MANIFEST_PATH.exists(), f"MANIFEST.json not found at {MANIFEST_PATH}"
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ============================================================================
# 1. MANIFEST & PROVENANCE INTEGRITY TESTS
# ============================================================================

def test_manifest_integrity_and_cryptographic_provenance():
    """Verify MANIFEST.json structure, exact SHA256 hashes, and baseline provenance."""
    manifest = _read_manifest()
    assert manifest.get("version") == "2.1.0"
    assert "provenance" in manifest

    baseline_doc = FIXTURES_DIR / manifest["baseline_document"]
    assert baseline_doc.exists()
    baseline_bytes = baseline_doc.read_bytes()
    expected_base_sha = manifest["baseline_sha256"]
    actual_base_sha = _sha256(baseline_bytes)
    assert actual_base_sha == expected_base_sha, f"Baseline SHA mismatch: {actual_base_sha} != {expected_base_sha}"

    fixtures = manifest.get("fixtures", [])
    assert len(fixtures) == 12, f"Expected 12 fixtures, got {len(fixtures)}"

    manifest_files = set()
    for entry in fixtures:
        fid = entry["fixture_id"]
        fname = entry["filename"]
        expected_sha = entry["sha256"]
        fixture_path = FIXTURES_DIR / fname

        assert fixture_path.exists(), f"Fixture file {fname} ({fid}) missing from disk"
        data = fixture_path.read_bytes()
        actual_sha = _sha256(data)
        assert actual_sha == expected_sha, f"Fixture {fname} SHA256 mismatch: {actual_sha} != {expected_sha}"
        assert entry["source_baseline_sha256"] == expected_base_sha

        manifest_files.add(fname)

        # Validate codepoint entries
        for cp_info in entry.get("inserted_codepoints", []):
            assert "codepoint" in cp_info
            assert "expected" in cp_info
            assert cp_info["codepoint"].startswith("U+")

    # Verify no unmanifested .docx files exist in corpus
    actual_docx_files = {p.name for p in FIXTURES_DIR.glob("*.docx")}
    unmanifested = actual_docx_files - manifest_files
    assert not unmanifested, f"Found unmanifested docx files in corpus: {unmanifested}"


# ============================================================================
# 2. POSITIVE CARRIER FIXTURE TESTS
# ============================================================================

def test_carrier_positive_zwsp():
    """Verify U+200B ZERO WIDTH SPACE is detected, planned, and cleanly removed."""
    raw = (FIXTURES_DIR / "carrier_zwsp.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert len(plan.text_mutations) == 3
    assert all(m.codepoint == 0x200B for m in plan.text_mutations)
    assert plan.changed_parts() == {"word/document.xml"}

    struct_before = _get_structure_counts(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is True
    assert rep["changed_parts"] == ["word/document.xml"]

    struct_after = _get_structure_counts(cleaned)
    assert struct_after["run_count"] == struct_before["run_count"], "Run count MUST be invariant"
    assert struct_after == struct_before, "All structural element counts MUST be invariant"

    cleaned_members = _get_zip_members_payload(cleaned)
    cleaned_doc_xml = cleaned_members["word/document.xml"].decode("utf-8")
    assert "\u200B" not in cleaned_doc_xml
    assert "ClearMarkSyntheticTest Document" in cleaned_doc_xml
    assert "TableRow 1 Cell 1" in cleaned_doc_xml


def test_carrier_positive_bidi_supported():
    """Verify supported bidi directional controls (LRM, RLM, LRE, PDF, LRI, PDI) are removed."""
    raw = (FIXTURES_DIR / "carrier_bidi_supported.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    expected_cps = {0x200E, 0x200F, 0x202A, 0x202C, 0x2066, 0x2069}
    detected_cps = {m.codepoint for m in plan.text_mutations}
    assert detected_cps == expected_cps
    assert len(plan.text_mutations) == 6

    struct_before = _get_structure_counts(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is True

    struct_after = _get_structure_counts(cleaned)
    assert struct_after["run_count"] == struct_before["run_count"], "Run count MUST be invariant"
    assert struct_after == struct_before

    cleaned_members = _get_zip_members_payload(cleaned)
    cleaned_doc_xml = cleaned_members["word/document.xml"].decode("utf-8")
    for cp in expected_cps:
        assert chr(cp) not in cleaned_doc_xml
    assert "Secondaryruninparagraph.Embedded" in cleaned_doc_xml


def test_carrier_positive_unicode_tags():
    """Verify Unicode Tag characters (U+E0001..U+E007F) are detected and removed."""
    raw = (FIXTURES_DIR / "carrier_unicode_tags.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    expected_cps = {0xE0001, 0xE0020, 0xE0041, 0xE007F}
    detected_cps = {m.codepoint for m in plan.text_mutations}
    assert detected_cps == expected_cps
    assert len(plan.text_mutations) == 4

    struct_before = _get_structure_counts(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is True

    struct_after = _get_structure_counts(cleaned)
    assert struct_after["run_count"] == struct_before["run_count"]
    assert struct_after == struct_before

    cleaned_doc_xml = _get_zip_members_payload(cleaned)["word/document.xml"].decode("utf-8")
    for cp in expected_cps:
        assert chr(cp) not in cleaned_doc_xml
    assert "Bookmarkedtextspantest" in cleaned_doc_xml


def test_carrier_positive_non_text_children_invariance():
    """Verify carriers adjacent to <w:br/>, <w:tab/>, and <w:br w:type='page'/> are removed without mutating non-text elements."""
    raw = (FIXTURES_DIR / "carrier_with_non_text_children.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert len(plan.text_mutations) == 3
    assert all(m.codepoint == 0x200B for m in plan.text_mutations)

    struct_before = _get_structure_counts(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is True

    struct_after = _get_structure_counts(cleaned)
    assert struct_after["run_count"] == struct_before["run_count"]
    assert struct_after["manual_page_break_count"] == struct_before["manual_page_break_count"]
    assert struct_after["tab_count"] == struct_before["tab_count"]
    assert struct_after == struct_before

    # Verify inside paragraph 4 that w:br, w:tab, and w:br w:type='page' still exist in original order
    cleaned_doc_xml = _get_zip_members_payload(cleaned)["word/document.xml"]
    root = ET.fromstring(cleaned_doc_xml)
    p4 = root.findall(".//w:p", NS)[3]  # 4th paragraph
    r1 = p4.findall(".//w:r", NS)[0]

    child_tags = [c.tag.split("}")[-1] for c in r1]
    assert "br" in child_tags
    assert "tab" in child_tags
    # Confirm the page break is specifically w:type="page"
    page_brs = [c for c in r1 if c.tag.endswith("br") and c.attrib.get(f"{{{W_NS}}}type") == "page"]
    assert len(page_brs) == 1
    assert "\u200B" not in ET.tostring(r1, encoding="utf-8").decode("utf-8")


def test_carrier_positive_mixed_parts():
    """Verify carriers in document body, table cell, header, and footer are removed across parts."""
    raw = (FIXTURES_DIR / "carrier_mixed.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert len(plan.text_mutations) == 6
    expected_parts = {"word/document.xml", "word/header1.xml", "word/footer1.xml"}
    assert plan.changed_parts() == expected_parts

    orig_members = _get_zip_members_payload(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is True
    assert set(rep["changed_parts"]) == expected_parts

    cleaned_members = _get_zip_members_payload(cleaned)

    # Document body text
    doc_text = cleaned_members["word/document.xml"].decode("utf-8")
    assert "\u200B" not in doc_text
    assert "\u00AD" not in doc_text
    assert "\u2060" not in doc_text
    assert "\uFEFF" not in doc_text
    assert "DocumentHeading" in doc_text
    assert "TableRow2" in doc_text

    # Header text
    hdr_text = cleaned_members["word/header1.xml"].decode("utf-8")
    assert "\u200B" not in hdr_text
    assert "HeaderSection Title" in hdr_text

    # Footer text
    ftr_text = cleaned_members["word/footer1.xml"].decode("utf-8")
    assert "\u200E" not in ftr_text
    assert "FooterPage Details" in ftr_text

    # Non-target members MUST have identical SHA256 hashes
    for mname in orig_members:
        if mname not in expected_parts:
            assert _sha256(cleaned_members[mname]) == _sha256(orig_members[mname]), (
                f"Non-target part {mname} payload was unexpectedly altered!"
            )


# ============================================================================
# 3. LEGITIMATE CONTEXTUAL UNICODE COUNTEREXAMPLE TESTS
# ============================================================================

def test_counterexample_emoji_zwj_preservation():
    """Verify legitimate emoji ZWJ sequences (family, profession, gendered) are preserved byte-for-byte."""
    raw = (FIXTURES_DIR / "counterexample_emoji_zwj.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    # Zero false positives
    assert plan.is_empty(), f"Detector produced false positive mutations: {plan.text_mutations}"
    assert len(plan.text_mutations) == 0

    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is False
    assert rep["mutations_count"] == 0
    assert rep["changed_parts"] == []

    # Zero modification: raw bytes identical
    assert cleaned == raw

    doc_text = _get_zip_members_payload(cleaned)["word/document.xml"].decode("utf-8")
    assert "👨‍👩‍👧" in doc_text
    assert "👩‍💻" in doc_text
    assert "👨‍🚀" in doc_text
    # Explicitly check codepoint presence
    assert "\u200D" in doc_text


def test_counterexample_arabic_joiner_preservation():
    """Verify legitimate Persian/Arabic ZWNJ (U+200C) and ZWJ (U+200D) are preserved in Arabic script."""
    raw = (FIXTURES_DIR / "counterexample_arabic_joiner.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert plan.is_empty(), f"False positive mutations detected: {plan.text_mutations}"
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is False
    assert cleaned == raw

    doc_text = _get_zip_members_payload(cleaned)["word/document.xml"].decode("utf-8")
    assert "می‌روم" in doc_text
    assert "\u0628\u200D\u0647" in doc_text
    assert "\u200C" in doc_text
    assert "\u200D" in doc_text


def test_counterexample_devanagari_preservation():
    """Verify legitimate Devanagari shaping conjuncts with ZWJ and ZWNJ are preserved byte-for-byte."""
    raw = (FIXTURES_DIR / "counterexample_devanagari.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert plan.is_empty(), f"False positive mutations detected: {plan.text_mutations}"
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is False
    assert cleaned == raw

    doc_text = _get_zip_members_payload(cleaned)["word/document.xml"].decode("utf-8")
    assert "क्‍ष" in doc_text
    assert "क्‌ष" in doc_text


def test_counterexample_nbsp_typography_preservation():
    """Verify U+00A0 NO-BREAK SPACE and U+202F NARROW NO-BREAK SPACE are preserved in SAFE mode."""
    raw = (FIXTURES_DIR / "counterexample_nbsp.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert plan.is_empty(), f"False positive mutations detected: {plan.text_mutations}"
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is False
    assert cleaned == raw

    doc_text = _get_zip_members_payload(cleaned)["word/document.xml"].decode("utf-8")
    assert "100\u00A0km" in doc_text
    assert "50\u202Fkg" in doc_text
    assert "Page\u00A042" in doc_text


def test_counterexample_nfc_nfd_preservation():
    """Verify NFC and NFD strings remain distinct and are not cross-normalized."""
    raw = (FIXTURES_DIR / "counterexample_nfc_nfd.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert plan.is_empty(), f"False positive mutations detected: {plan.text_mutations}"
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is False
    assert cleaned == raw

    doc_text = _get_zip_members_payload(cleaned)["word/document.xml"].decode("utf-8")
    assert "Ti\u1EBFng Vi\u1EC7t" in doc_text
    assert "Tie\u0302\u0301ng Vie\u0302\u0323t" in doc_text


# ============================================================================
# 4. COMBINED POSITIVE + LEGITIMATE CONTEXT GATE
# ============================================================================

def test_carrier_and_legitimate_unicode_combined_gate():
    """Primary Gate: Simultaneously verifies removable carrier deletion and legitimate Unicode preservation."""
    raw = (FIXTURES_DIR / "carrier_and_legitimate_unicode.docx").read_bytes()
    pkg = DocxPackage(raw)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    # Must detect exactly the 4 removable carriers
    expected_cps = [0x200B, 0x00AD, 0x200E, 0xE0020]
    detected_cps = [m.codepoint for m in plan.text_mutations]
    assert detected_cps == expected_cps
    assert len(plan.text_mutations) == 4

    struct_before = _get_structure_counts(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep["changed"] is True
    assert rep["changed_parts"] == ["word/document.xml"]

    struct_after = _get_structure_counts(cleaned)
    assert struct_after["run_count"] == struct_before["run_count"]
    assert struct_after == struct_before

    doc_text = _get_zip_members_payload(cleaned)["word/document.xml"].decode("utf-8")

    # Positive removals: carriers are completely gone
    for cp in expected_cps:
        assert chr(cp) not in doc_text

    # Legitimate counterexamples: preserved byte-for-byte in the exact same paragraph
    assert "👨‍👩‍👧" in doc_text
    assert "می‌روم" in doc_text
    assert "क्‍ष" in doc_text
    assert "100\u00A0km" in doc_text
    assert "withcarriertags" in doc_text


# ============================================================================
# 5. STRUCTURAL INVARIANTS & NON-TARGET PRESERVATION ACROSS ALL FIXTURES
# ============================================================================

@pytest.mark.parametrize(
    "fixture_name",
    [
        "synthetic_baseline.docx",
        "carrier_zwsp.docx",
        "carrier_bidi_supported.docx",
        "carrier_unicode_tags.docx",
        "carrier_with_non_text_children.docx",
        "carrier_mixed.docx",
        "counterexample_emoji_zwj.docx",
        "counterexample_arabic_joiner.docx",
        "counterexample_devanagari.docx",
        "counterexample_nbsp.docx",
        "counterexample_nfc_nfd.docx",
        "carrier_and_legitimate_unicode.docx",
    ],
)
def test_all_fixtures_structural_invariants_and_run_count(fixture_name):
    """Assert run_count, paragraph, table, cell, break, bookmark, and hyperlink invariance on all fixtures."""
    raw = (FIXTURES_DIR / fixture_name).read_bytes()
    struct_before = _get_structure_counts(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    struct_after = _get_structure_counts(cleaned)

    assert struct_after["run_count"] == struct_before["run_count"], (
        f"Fixture {fixture_name}: run count changed from {struct_before['run_count']} to {struct_after['run_count']}!"
    )
    assert struct_after == struct_before, (
        f"Fixture {fixture_name}: structural counts changed! Before: {struct_before}, After: {struct_after}"
    )


@pytest.mark.parametrize(
    "fixture_name",
    [
        "synthetic_baseline.docx",
        "carrier_zwsp.docx",
        "carrier_bidi_supported.docx",
        "carrier_unicode_tags.docx",
        "carrier_with_non_text_children.docx",
        "carrier_mixed.docx",
        "counterexample_emoji_zwj.docx",
        "counterexample_arabic_joiner.docx",
        "counterexample_devanagari.docx",
        "counterexample_nbsp.docx",
        "counterexample_nfc_nfd.docx",
        "carrier_and_legitimate_unicode.docx",
    ],
)
def test_all_fixtures_non_target_zip_member_payload_identity(fixture_name):
    """Verify that every member not in changed_parts has an identical SHA256 before and after cleaning."""
    raw = (FIXTURES_DIR / fixture_name).read_bytes()
    orig_members = _get_zip_members_payload(raw)
    cleaned, rep = clean_docx_lossless(raw, {"mode": "SAFE"})
    cleaned_members = _get_zip_members_payload(cleaned)

    changed_parts = set(rep.get("changed_parts", []))
    for mname, orig_payload in orig_members.items():
        if mname not in changed_parts:
            assert mname in cleaned_members, f"Part {mname} missing from cleaned output!"
            assert _sha256(cleaned_members[mname]) == _sha256(orig_payload), (
                f"Fixture {fixture_name}: Non-target member {mname} changed unexpectedly!"
            )


def test_xml_space_preserve_retained():
    """Verify xml:space='preserve' attribute and surrounding whitespace are intact after cleaning."""
    raw = (FIXTURES_DIR / "carrier_with_non_text_children.docx").read_bytes()
    cleaned, _ = clean_docx_lossless(raw, {"mode": "SAFE"})

    root = ET.fromstring(_get_zip_members_payload(cleaned)["word/document.xml"])
    preserved_nodes = root.findall(".//*[@{http://www.w3.org/XML/1998/namespace}space='preserve']")
    assert len(preserved_nodes) >= 1

    # Check node text retained leading/trailing whitespace
    for node in preserved_nodes:
        if node.text:
            assert node.text.startswith(" ") or node.text.endswith(" ") or node.text.startswith("\t")


def test_detector_truthfulness_zero_fp_zero_fn():
    """Assert total false positives = 0 and total false negatives = 0 across the corpus."""
    manifest = _read_manifest()
    total_fp = 0
    total_fn = 0

    for entry in manifest["fixtures"]:
        fname = entry["filename"]
        raw = (FIXTURES_DIR / fname).read_bytes()
        pkg = DocxPackage(raw)
        plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

        inserted = entry.get("inserted_codepoints", [])
        expected_remove_cps = [
            int(cp["codepoint"].replace("U+", ""), 16)
            for cp in inserted
            if cp.get("expected") == "REMOVE"
        ]
        detected_cps = [m.codepoint for m in plan.text_mutations]

        # False negatives: expected removable codepoints not detected
        fn_for_fixture = len(expected_remove_cps) - len(detected_cps)
        if fn_for_fixture > 0:
            total_fn += fn_for_fixture

        # False positives: detected mutations when none were inserted
        if not expected_remove_cps and detected_cps:
            total_fp += len(detected_cps)

    assert total_fp == 0, f"Detected {total_fp} false positive carrier mutations"
    assert total_fn == 0, f"Detected {total_fn} false negative carrier mutations"


# ============================================================================
# 6. PIPELINE INSPECTION, DRY-RUN, CLI, IDEMPOTENCE & PRIVACY
# ============================================================================

def test_pipeline_inspect_and_dry_run_parity():
    """Verify Pipeline.inspect() and Pipeline.clean(dry_run=True) parity on mixed carrier fixture."""
    fixture_path = FIXTURES_DIR / "carrier_and_legitimate_unicode.docx"
    pipeline = Pipeline()

    # 1. Pipeline.inspect
    insp_report = pipeline.inspect(fixture_path, mode=ProcessingMode.SAFE)
    assert insp_report.status.value in ("INSPECTED", "WATERMARKED")
    assert insp_report.inspection.detection_status.value == "DETECTED"
    assert len(insp_report.inspection.findings) > 0

    # 2. Pipeline.clean(dry_run=True)
    dry_bytes, dry_report = pipeline.clean(
        fixture_path,
        mode=ProcessingMode.SAFE,
        dry_run=True,
    )
    assert dry_bytes == fixture_path.read_bytes(), "Dry-run output bytes must match original bytes exactly"
    assert dry_report.output.changed is False
    assert dry_report.output.would_change is True
    assert dry_report.status.value in ("INSPECTED", "NO_CHANGE_REQUIRED")

    # 3. Parity with real clean
    real_bytes, real_report = pipeline.clean(
        fixture_path,
        mode=ProcessingMode.SAFE,
        dry_run=False,
    )
    assert real_report.output.changed is True
    assert real_report.output.would_change is True
    assert len(dry_report.mutation_plan.mutations) == len(real_report.mutation_plan.mutations)


def test_cli_integration_sanity(tmp_path):
    """Verify watermarks CLI inspect and clean --dry-run on a positive carrier fixture."""
    fixture_path = FIXTURES_DIR / "carrier_zwsp.docx"

    # CLI inspect --json
    res_insp = subprocess.run(
        [sys.executable, "-m", "service.scripts.cli", "inspect", str(fixture_path), "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_insp.returncode in (0, 1)
    insp_data = json.loads(res_insp.stdout)
    assert insp_data["status"] == "INSPECTED"
    assert insp_data["inspection"]["detection_status"] == "DETECTED"
    assert len(insp_data["inspection"]["findings"]) == 3

    # CLI clean --dry-run --json
    res_clean = subprocess.run(
        [sys.executable, "-m", "service.scripts.cli", "clean", str(fixture_path), "--dry-run", "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_clean.returncode == 0
    clean_data = json.loads(res_clean.stdout)
    assert clean_data["output"]["changed"] is False
    assert clean_data["output"]["would_change"] is True
    assert len(clean_data["mutation_plan"]["mutations"]) == 3


def test_docx_cleaning_idempotence():
    """Verify that a second clean pass reports NO_CHANGE_REQUIRED / changed=False."""
    raw = (FIXTURES_DIR / "carrier_and_legitimate_unicode.docx").read_bytes()
    cleaned_pass1, rep1 = clean_docx_lossless(raw, {"mode": "SAFE"})
    assert rep1["changed"] is True

    cleaned_pass2, rep2 = clean_docx_lossless(cleaned_pass1, {"mode": "SAFE"})
    assert rep2["changed"] is False
    assert rep2["mutations_count"] == 0
    assert rep2["changed_parts"] == []
    assert cleaned_pass2 == cleaned_pass1


def test_zero_network_during_docx_carrier_processing(monkeypatch):
    """Ensure zero network socket connections occur during inspection or cleaning."""
    def _forbidden_connect(*args, **kwargs):
        raise AssertionError("CRITICAL: Network socket connection attempted during DOCX processing!")

    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)

    fixture_path = FIXTURES_DIR / "carrier_and_legitimate_unicode.docx"
    raw = fixture_path.read_bytes()
    clean_docx_lossless(raw, {"mode": "SAFE"})
    pipeline = Pipeline()
    pipeline.inspect(fixture_path, mode=ProcessingMode.SAFE)
    pipeline.clean(fixture_path, mode=ProcessingMode.SAFE, dry_run=True)


def test_report_privacy_no_body_text_leak():
    """Ensure generated cleaning reports do not expose full document text or run payloads."""
    fixture_path = FIXTURES_DIR / "carrier_and_legitimate_unicode.docx"
    pipeline = Pipeline()
    _, rep = pipeline.clean(fixture_path, mode=ProcessingMode.SAFE)
    rep_dict = rep.to_dict()
    rep_json = json.dumps(rep_dict)

    # Document body text phrases must NOT be leaked in report
    assert "Emoji: 👨‍👩‍👧" not in rep_json
    assert "Persian: می‌روم" not in rep_json
    assert "Devanagari: क्‍ष" not in rep_json
    assert "Secondary run in paragraph" not in rep_json


# ============================================================================
# 7. GOLDEN REGRESSION & FROZEN CORE IMMUTABILITY
# ============================================================================

def test_golden_v20_regression_and_frozen_core_diff():
    """Verify Golden v2.0 hash locks, candidate hash lock, and empty git diff on frozen core."""
    golden_path = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
    candidate_path = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"

    assert golden_path.exists()
    assert candidate_path.exists()

    actual_golden_sha = _sha256(golden_path.read_bytes())
    actual_candidate_sha = _sha256(candidate_path.read_bytes())

    assert actual_golden_sha == GOLDEN_ORIGINAL_SHA, f"Golden SHA mismatch: {actual_golden_sha}"
    assert actual_candidate_sha == CANDIDATE_OUTPUT_SHA, f"Candidate SHA mismatch: {actual_candidate_sha}"

    # Verify frozen core has zero diff against v2.0.0 tag
    res_diff = subprocess.run(
        ["git", "diff", "v2.0.0", "--", "service/scripts/docx/"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_diff.returncode == 0
    assert res_diff.stdout.strip() == "", f"service/scripts/docx/ MUST be unmodified! Diff:\n{res_diff.stdout}"
