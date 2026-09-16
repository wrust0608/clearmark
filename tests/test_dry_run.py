"""Tests for Phase 2: Dry-Run Correctness & Zero-Write Guarantees (Sections 1, 5, 6, 12, 13, 15, 16, 18).

Invariants Verified:
1. Zero-Write Invariant: dry_run=True never calls any write primitive, never modifies input, and never creates temp files.
2. Plan Parity Invariant: dry_run mutation_plan == real clean pre-execution mutation_plan for same input, policy, and mode.
3. Status & Would-Change Invariant:
   - empty plan -> status=NO_CHANGE_REQUIRED, changed=False, would_change=False
   - non-empty plan -> status=INSPECTED, changed=False, would_change=True
4. Privacy Invariant: Serialized dry-run reports contain hashes, counts, and codepoints, but zero body text.
5. Zero-Network Invariant: All dry-run operations run strictly locally with zero network socket activity.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
from pathlib import Path
import socket
import pytest

from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import (
    CleaningReport,
    DetectionStatus,
    PipelineStatus,
    ProcessingMode,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CANDIDATE_DOCX = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"


def test_dry_run_zero_write_guarantee(tmp_path, monkeypatch):
    """Section 6: For dry_run=True prove input bytes, size, and mtime are unchanged, and no write primitive is invoked."""
    test_docx = tmp_path / "target.docx"
    test_docx.write_bytes(GOLDEN_DOCX.read_bytes())

    stat_before = test_docx.stat()
    sha_before = hashlib.sha256(test_docx.read_bytes()).hexdigest()
    dir_entries_before = set(tmp_path.iterdir())

    # Mock all write-capable operations to fail loudly if invoked during dry-run
    def _forbidden_write(*args, **kwargs):
        raise AssertionError("CRITICAL: Write primitive was invoked during dry_run=True!")

    import service.scripts.common as common_mod
    monkeypatch.setattr(common_mod, "safe_write_bytes", _forbidden_write)
    monkeypatch.setattr(os, "replace", _forbidden_write)

    orig_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        if any(w in mode for w in ("w", "a", "+", "x")):
            raise AssertionError(f"CRITICAL: Write open mode '{mode}' invoked during dry_run=True on {file}!")
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _guarded_open)

    pipeline = Pipeline()
    cleaned_bytes, report = pipeline.clean(
        test_docx,
        output_path=tmp_path / "forbidden_output.docx",
        dry_run=True,
        in_place=True,
    )

    stat_after = test_docx.stat()
    sha_after = hashlib.sha256(test_docx.read_bytes()).hexdigest()
    dir_entries_after = set(tmp_path.iterdir())

    # Invariant assertions
    assert sha_after == sha_before
    assert stat_after.st_size == stat_before.st_size
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns
    assert dir_entries_after == dir_entries_before
    assert not (tmp_path / "forbidden_output.docx").exists()
    assert cleaned_bytes == test_docx.read_bytes()
    assert report.output.changed is False
    assert report.output.would_change is True


def test_dry_run_mutation_plan_parity_with_real_clean():
    """Section 5: Invariant: dry_run mutation_plan == real clean pre-execution mutation_plan."""
    pipeline = Pipeline()

    # 1. Run dry-run on Golden DOCX
    _, dry_report = pipeline.clean(GOLDEN_DOCX, dry_run=True, mode=ProcessingMode.SAFE)

    # 2. Run real clean on Golden DOCX
    _, real_report = pipeline.clean(GOLDEN_DOCX, dry_run=False, mode=ProcessingMode.SAFE)

    # Mutations in dry-run must exactly equal mutations planned for real clean
    assert dry_report.mutation_plan.mutations == real_report.mutation_plan.mutations
    assert dry_report.mutation_plan.changed_parts == real_report.mutation_plan.changed_parts
    assert len(dry_report.mutation_plan.mutations) > 0


def test_dry_run_status_and_would_change_semantics():
    """Section 12 & 13: Differentiate empty plan (NO_CHANGE_REQUIRED) vs non-empty dry-run (INSPECTED, would_change=True)."""
    pipeline = Pipeline()

    # Case A: Non-empty plan (Golden DOCX needs metadata scrub)
    _, rep_dirty = pipeline.clean(GOLDEN_DOCX, dry_run=True)
    assert rep_dirty.status == PipelineStatus.INSPECTED
    assert rep_dirty.output.changed is False
    assert rep_dirty.output.would_change is True
    assert any("Dry-run mode" in w for w in rep_dirty.validation.warnings)

    # Case B: Empty plan (Candidate DOCX already cleaned)
    _, rep_clean = pipeline.clean(CANDIDATE_DOCX, dry_run=True)
    assert rep_clean.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert rep_clean.output.changed is False
    assert rep_clean.output.would_change is False
    assert len(rep_clean.mutation_plan.mutations) == 0


def test_dry_run_synthetic_carrier_preview(tmp_path):
    """Section 7 & 18: Synthetic carrier preview reports precise planned removals without modifying input."""
    sample = tmp_path / "carrier.txt"
    sample.write_text("Hello\u200bWorld\ufeff!", encoding="utf-8")

    pipeline = Pipeline()
    cleaned_bytes, report = pipeline.clean(sample, dry_run=True)

    assert report.status == PipelineStatus.INSPECTED
    assert report.output.changed is False
    assert report.output.would_change is True
    assert cleaned_bytes == sample.read_bytes()
    assert len(report.mutation_plan.mutations) > 0


def test_dry_run_zero_network_isolation(monkeypatch):
    """Section 16: Assert zero network attempts during dry_run=True."""
    def _forbidden_network(*args, **kwargs):
        raise RuntimeError("CRITICAL: Network call attempted during dry-run!")

    monkeypatch.setattr(socket, "socket", _forbidden_network)

    pipeline = Pipeline()
    _, rep = pipeline.clean(GOLDEN_DOCX, dry_run=True)
    assert rep.privacy.network_used is False
    assert rep.status == PipelineStatus.INSPECTED


def test_dry_run_report_privacy_across_fixtures(tmp_path):
    """Section 15: Verify serialized dry-run and inspect reports never contain full document text."""
    pipeline = Pipeline()

    # Test Golden DOCX
    _, rep_docx = pipeline.clean(GOLDEN_DOCX, dry_run=True)
    json_docx = json.dumps(rep_docx.to_dict(), ensure_ascii=False)

    for forbidden in ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA", "chất lượng công trình", "nghiệm thu"):
        assert forbidden not in json_docx
        assert forbidden.lower() not in json_docx.lower()

    # Test text fixture with secret message
    secret_text = tmp_path / "confidential.txt"
    secret_text.write_text("SUPER_SECRET_PAYLOAD_STRING \u200b with carrier", encoding="utf-8")
    _, rep_txt = pipeline.clean(secret_text, dry_run=True)
    json_txt = json.dumps(rep_txt.to_dict(), ensure_ascii=False)

    assert "SUPER_SECRET_PAYLOAD_STRING" not in json_txt
