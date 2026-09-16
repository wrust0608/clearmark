"""Tests for Phase 1: Unified Data Model, Structured CleaningReport, and Format Policy Registry."""

from __future__ import annotations

import json
import pytest

from service.scripts.format_policy import (
    FormatPolicy,
    FormatPolicyRegistry,
)
from service.scripts.pipeline_types import (
    CleaningReport,
    ErrorCode,
    FidelityLevel,
    FileIdentity,
    InspectionData,
    MutationRecord,
    OutputRecord,
    PipelineStatus,
    PolicySelection,
    PrivacySummary,
    ProcessingMode,
    ValidationOutcome,
)



def test_pipeline_status_enum():
    """Verify all six mandatory high-level pipeline states exist."""
    assert PipelineStatus.INSPECTED.value == "INSPECTED"
    assert PipelineStatus.NO_CHANGE_REQUIRED.value == "NO_CHANGE_REQUIRED"
    assert PipelineStatus.CLEANED.value == "CLEANED"
    assert PipelineStatus.VALIDATION_FAILED.value == "VALIDATION_FAILED"
    assert PipelineStatus.UNSUPPORTED.value == "UNSUPPORTED"
    assert PipelineStatus.ERROR.value == "ERROR"


def test_error_code_enum():
    """Verify machine-readable error codes are defined."""
    expected = {
        "UNSUPPORTED_FORMAT",
        "INVALID_CONTAINER",
        "VALIDATION_FAILED",
        "OPTIONAL_DEPENDENCY_MISSING",
        "UNSUPPORTED_ARCHIVE_FEATURE",
        "PROCESSING_LIMIT_EXCEEDED",
        "INTERNAL_ERROR",
    }
    actual = {e.value for e in ErrorCode}
    assert expected.issubset(actual)


def test_processing_modes():
    """Verify processing modes: SAFE, BALANCED, AGGRESSIVE."""
    assert ProcessingMode.SAFE.value == "SAFE"
    assert ProcessingMode.BALANCED.value == "BALANCED"
    assert ProcessingMode.AGGRESSIVE.value == "AGGRESSIVE"


def test_fidelity_levels():
    """Verify fidelity levels A through D."""
    assert FidelityLevel.LEVEL_A.value == "LEVEL_A"  # Byte-preserving non-target parts
    assert FidelityLevel.LEVEL_B.value == "LEVEL_B"  # Structural invariants
    assert FidelityLevel.LEVEL_C.value == "LEVEL_C"  # Semantic/content invariants
    assert FidelityLevel.LEVEL_D.value == "LEVEL_D"  # Visual rendering regression


def test_cleaning_report_schema_and_serialization():
    """Verify CleaningReport conforms strictly to Section 5 specification."""
    report = CleaningReport(
        status=PipelineStatus.CLEANED,
        input=FileIdentity(
            filename="document.docx",
            format="docx",
            size=49959,
            sha256="c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d",
        ),
        inspection=InspectionData(
            findings=["AI vendor metadata in docProps/app.xml"],
            detectors_run=["DocxDetector", "docProps"],
            detectors_unavailable=[],
        ),
        policy=PolicySelection(
            mode=ProcessingMode.SAFE,
            format_policy="docx",
            normalize_spaces=False,
            remote_processing=False,
        ),
        mutation_plan=MutationRecord(
            mutations=[{"action": "drop_meta_part", "target": "docProps/custom.xml"}],
            changed_parts=["docProps/app.xml", "docProps/custom.xml"],
        ),
        validation=ValidationOutcome(
            status="PASS",
            invariants=["paragraphs:204->204", "runs:288->288", "pages:19->19", "raw_opc:pass"],
            warnings=[],
        ),
        output=OutputRecord(
            changed=True,
            size=49395,
            sha256="7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297",
            output_path="document.cleaned.docx",
        ),
        privacy=PrivacySummary(
            network_used=False,
            external_services=[],
        ),
        performance_elapsed_ms=231.12,
    )

    d = report.to_dict()
    assert d["status"] == "CLEANED"
    assert d["input"]["filename"] == "document.docx"
    assert d["input"]["format"] == "docx"
    assert d["input"]["size"] == 49959
    assert d["policy"]["mode"] == "SAFE"
    assert d["policy"]["normalize_spaces"] is False
    assert d["privacy"]["network_used"] is False
    assert d["performance"]["elapsed_ms"] == 231.12
    assert d["validation"]["status"] == "PASS"

    # Verify JSON serialization works seamlessly
    raw_json = json.dumps(d)
    deserialized = json.loads(raw_json)
    assert deserialized["status"] == "CLEANED"
    assert deserialized["output"]["changed"] is True


def test_cleaning_report_never_contains_full_document_text():
    """Verify document body text cannot be stored in the report."""
    report = CleaningReport(
        status=PipelineStatus.NO_CHANGE_REQUIRED,
        input=FileIdentity(
            filename="sample.txt",
            format="txt",
            size=1000,
            sha256="abc123",
        ),
        inspection=InspectionData(),
        policy=PolicySelection(
            mode=ProcessingMode.SAFE,
            format_policy="txt",
            normalize_spaces=True,
            remote_processing=False,
        ),
        mutation_plan=MutationRecord(),
        validation=ValidationOutcome(status="PASS"),
        output=OutputRecord(
            changed=False,
            size=1000,
            sha256="abc123",
        ),
        privacy=PrivacySummary(),
        performance_elapsed_ms=1.5,
    )

    d = report.to_dict()
    # Check that forbidden text payload fields do not exist
    for forbidden_key in ("text", "content", "body", "full_text", "document_text", "raw_text"):
        assert forbidden_key not in d, f"Forbidden content key '{forbidden_key}' present in CleaningReport!"


def test_format_policy_registry():
    """Verify FormatPolicyRegistry contains explicit policies for all key formats."""
    reg = FormatPolicyRegistry.get_default()

    docx_pol = reg.get("docx")
    assert docx_pol is not None
    assert docx_pol.format_name == "docx"
    assert ".docx" in docx_pol.extensions
    assert FidelityLevel.LEVEL_A in docx_pol.fidelity_requirements
    assert FidelityLevel.LEVEL_B in docx_pol.fidelity_requirements
    assert FidelityLevel.LEVEL_C in docx_pol.fidelity_requirements
    assert FidelityLevel.LEVEL_D in docx_pol.fidelity_requirements
    assert docx_pol.default_mode == ProcessingMode.SAFE
    assert docx_pol.allow_destructive_normalization is False

    xlsx_pol = reg.get("xlsx")
    assert xlsx_pol is not None
    assert ".xlsx" in xlsx_pol.extensions
    assert FidelityLevel.LEVEL_A in xlsx_pol.fidelity_requirements
    assert FidelityLevel.LEVEL_B in xlsx_pol.fidelity_requirements

    pptx_pol = reg.get("pptx")
    assert pptx_pol is not None
    assert ".pptx" in pptx_pol.extensions
    assert FidelityLevel.LEVEL_A in pptx_pol.fidelity_requirements
    assert FidelityLevel.LEVEL_B in pptx_pol.fidelity_requirements

    png_pol = reg.get("png")
    assert png_pol is not None
    assert ".png" in png_pol.extensions
    assert "EXIF" in png_pol.clean_capabilities or "metadata" in png_pol.clean_capabilities


def test_format_policy_single_source_of_truth():
    """Verify service/scripts/format_policy.py is the single authoritative source of truth."""
    from service.scripts.format_policy import (
        FormatCapabilities,
        FormatPolicy as FP_Policy,
        FormatPolicyRegistry as FP_Registry,
    )
    from service.scripts import pipeline_types

    # pipeline_types forwards to format_policy without owning a duplicate class
    assert pipeline_types.FormatPolicyRegistry is FP_Registry
    assert pipeline_types.FormatPolicy is FP_Policy
    assert pipeline_types.FormatCapabilities is FormatCapabilities

    # Authoritative registry instance has format policies
    reg = FP_Registry.get_default()
    assert reg.get("docx") is not None
    assert reg.get("xlsx") is not None
    assert reg.get("pdf") is not None
    assert reg.get("png") is not None


def test_cleaning_report_privacy_regression_scanning_golden_fixture():
    """Section 13: Regression test scanning serialized CleaningReport for known fixture text."""
    from pathlib import Path
    from service.scripts.pipeline import Pipeline

    golden_path = Path("01_GOLDEN_ORIGINAL_UNTOUCHED.docx")
    assert golden_path.exists(), "Golden fixture document must exist"

    pipeline = Pipeline()
    # 1. Inspection report
    insp_report = pipeline.inspect(golden_path)
    insp_json = json.dumps(insp_report.to_dict(), ensure_ascii=False)

    # 2. Cleaning report
    _, clean_report = pipeline.clean(golden_path)
    clean_json = json.dumps(clean_report.to_dict(), ensure_ascii=False)

    # Known Vietnamese document text fragments present in 01_GOLDEN_ORIGINAL_UNTOUCHED.docx
    fixture_phrases = [
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
        "Độc lập - Tự do - Hạnh phúc",
        "BÁO CÁO",
        "chất lượng công trình",
        "nghiệm thu",
        "chủ đầu tư",
        "thi công",
        "tiêu chuẩn",
    ]

    for phrase in fixture_phrases:
        assert phrase not in insp_json, f"Fixture text '{phrase}' leaked into inspect CleaningReport JSON!"
        assert phrase not in clean_json, f"Fixture text '{phrase}' leaked into clean CleaningReport JSON!"
        assert phrase.lower() not in insp_json.lower(), f"Case-insensitive fixture text '{phrase}' leaked into inspect CleaningReport JSON!"
        assert phrase.lower() not in clean_json.lower(), f"Case-insensitive fixture text '{phrase}' leaked into clean CleaningReport JSON!"

