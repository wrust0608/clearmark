"""Tests for Phase 1: Unified File Workflow Pipeline Engine (Sections 3, 4, 9, 10, 20)."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import pytest

from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import (
    CleaningReport,
    PipelineStatus,
    ProcessingMode,
    ErrorCode,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CANDIDATE_DOCX = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"
EXPECTED_GOLDEN_SHA256 = "c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d"
EXPECTED_CANDIDATE_SHA256 = "7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297"


def test_pipeline_inspect_docx_golden():
    """Verify inspection on True Golden DOCX produces INSPECTED status and never modifies anything."""
    pipeline = Pipeline()
    report = pipeline.inspect(GOLDEN_DOCX)

    assert report.status == PipelineStatus.INSPECTED
    assert report.input.filename == GOLDEN_DOCX.name
    assert report.input.format == "docx"
    assert report.input.size == 49959
    assert report.input.sha256 == EXPECTED_GOLDEN_SHA256
    assert len(report.inspection.findings) > 0
    assert "DocxDetector" in report.inspection.detectors_run
    assert report.output.changed is False
    assert report.output.size == 49959
    assert report.output.sha256 == EXPECTED_GOLDEN_SHA256


def test_pipeline_clean_docx_golden_matches_approved_candidate():
    """Verify clean() on True Golden DOCX reproduces the canonical candidate byte-identically."""
    pipeline = Pipeline()
    cleaned_bytes, report = pipeline.clean(GOLDEN_DOCX, mode=ProcessingMode.SAFE)

    assert report.status == PipelineStatus.CLEANED
    assert report.output.changed is True
    assert report.output.size == 49395
    assert report.output.sha256 == EXPECTED_CANDIDATE_SHA256
    assert hashlib.sha256(cleaned_bytes).hexdigest() == EXPECTED_CANDIDATE_SHA256
    assert report.validation.status == "PASS"
    assert report.privacy.network_used is False


def test_pipeline_idempotence_on_candidate():
    """Verify second clean pass on already cleaned file reports NO_CHANGE_REQUIRED."""
    pipeline = Pipeline()
    cleaned_bytes, report = pipeline.clean(CANDIDATE_DOCX, mode=ProcessingMode.SAFE)

    assert report.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert report.output.changed is False
    assert report.output.size == 49395
    assert report.output.sha256 == EXPECTED_CANDIDATE_SHA256
    assert hashlib.sha256(cleaned_bytes).hexdigest() == EXPECTED_CANDIDATE_SHA256


def test_pipeline_dry_run_produces_plan_without_output():
    """Verify dry_run=True computes plan and validation feasibility without mutating."""
    pipeline = Pipeline()
    cleaned_bytes, report = pipeline.clean(GOLDEN_DOCX, dry_run=True)

    assert report.status == PipelineStatus.INSPECTED
    assert len(report.mutation_plan.mutations) > 0
    assert report.output.changed is False
    assert cleaned_bytes == GOLDEN_DOCX.read_bytes()


def test_pipeline_unsupported_format():
    """Verify unsupported binary files fail closed with UNSUPPORTED status."""
    pipeline = Pipeline()
    fake_data = b"\x00\x01\x02\x03\x04\x05\x06\x07_UNKNOWN_FORMAT_DATA"
    report = pipeline.inspect(fake_data, filename="mystery.xyz")

    assert report.status == PipelineStatus.UNSUPPORTED
    assert report.error_code == ErrorCode.UNSUPPORTED_FORMAT


def test_pipeline_safe_in_place_atomic(tmp_path):
    """Verify in-place cleaning atomically replaces the original file on pass."""
    test_file = tmp_path / "document.docx"
    test_file.write_bytes(GOLDEN_DOCX.read_bytes())

    pipeline = Pipeline()
    cleaned_bytes, report = pipeline.clean(test_file, in_place=True)

    assert report.status == PipelineStatus.CLEANED
    assert test_file.stat().st_size == 49395
    assert hashlib.sha256(test_file.read_bytes()).hexdigest() == EXPECTED_CANDIDATE_SHA256
