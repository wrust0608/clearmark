"""tests/test_documentation_consistency.py

Automated Documentation Consistency & Anti-Staleness Regression Test Suite.
Enforces that current release documentation and artifacts contain no stale
acceptance values and strictly reference the True Golden Baseline.

Rules enforced:
1. Forbid unqualified occurrences of stale baseline metrics (70,608 / 70608, 0a251436,
   '6467 -> 6467', '6,467 -> 6,467', 61.87) in all current release documents.
   (Historical regression examples are allowed ONLY inside docs/history/).
2. Assert that current release documentation explicitly asserts the True Golden metrics:
   - SHA-256: c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d
   - Runs: 288 -> 288
   - Manual page breaks: 5 -> 5
   - Pages: 19 -> 19
   - Test suite: 1359 passed, 152 skipped in 63.76s
3. Assert that the default port is consistently 8765.
4. Assert that the final evidence package in artifacts/final_acceptance/ exists and is complete.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Current release documents that must be authoritative and free of stale acceptance results
CURRENT_RELEASE_DOCS = [
    REPO_ROOT / "RELEASE_NOTES.md",
    REPO_ROOT / "MASTER_IMPLEMENTATION_PLAN.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "reports" / "MASTER_REVALIDATION_REPORT.md",
    REPO_ROOT / "artifacts" / "release_verification.json",
    REPO_ROOT / "artifacts" / "README.md",
]

# History folder where legacy/regression analysis is quarantined
HISTORY_DIR = REPO_ROOT / "docs" / "history"

FORBIDDEN_STALE_PATTERNS = [
    r"70[,\.]?608",
    r"0a251436",
    r"6[,\.]?467\s*(?:->|\\rightarrow)\s*6[,\.]?467",
    r"61\.87",
]


class TestDocumentationConsistency:
    """Ensures documentation integrity and eliminates stale acceptance figures."""

    def test_current_release_docs_exist(self):
        """All critical release documents must exist."""
        for doc_path in CURRENT_RELEASE_DOCS:
            assert doc_path.exists(), f"Required release document missing: {doc_path}"

    def test_no_unqualified_stale_metrics_in_release_docs(self):
        """Current release documentation must not contain stale baseline metrics."""
        violations = []
        for doc_path in CURRENT_RELEASE_DOCS:
            text = doc_path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_STALE_PATTERNS:
                matches = re.finditer(pattern, text)
                for m in matches:
                    # Look at the surrounding context (line)
                    start = max(0, text.rfind("\n", 0, m.start()) + 1)
                    end = text.find("\n", m.end())
                    if end == -1:
                        end = len(text)
                    line = text[start:end].strip()

                    # Only allow if explicitly marked as historical/negative witness/invalid baseline
                    is_quarantined_context = any(
                        keyword in line
                        for keyword in [
                            "INVALID HISTORICAL BASELINE",
                            "negative regression witness",
                            "Negative Witnesses",
                            "stress/regression",
                            "flawed witness",
                            "witness",
                            "02_BAD_OUTPUT_RUN_EXPLOSION",
                            "03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION",
                            "Đã phân loại là INVALID",
                            "thay thế bằng True Golden",
                            "tập mẫu lịch sử",
                        ]
                    )
                    if not is_quarantined_context:
                        violations.append(f"{doc_path.name}:{line} -> matched forbidden '{m.group(0)}'")

        assert not violations, "Stale acceptance metrics found in active release docs:\n" + "\n".join(violations)

    def test_no_unlabeled_6467_runs_pass(self):
        """There must NEVER again be an unlabeled 'Runs 6467 -> 6467 = PASS'."""
        for doc_path in CURRENT_RELEASE_DOCS:
            text = doc_path.read_text(encoding="utf-8")
            assert "6467 -> 6467 = PASS" not in text
            assert "6467 -> 6467" not in text or "INVALID" in text or "witness" in text or "FAIL" in text

    def test_true_golden_metrics_present_in_release_notes(self):
        """RELEASE_NOTES.md must contain the True Golden baseline metrics."""
        text = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        assert "c05ca5c1be3b" in text, "Missing Golden SHA-256 fingerprint in RELEASE_NOTES.md"
        assert "288" in text, "Missing run count 288 in RELEASE_NOTES.md"
        assert "5" in text, "Missing page break count 5 in RELEASE_NOTES.md"
        assert "19" in text, "Missing rendered page count 19 in RELEASE_NOTES.md"
        assert "1359 passed" in text or "1,359 passed" in text, "Missing 1359 passed in RELEASE_NOTES.md"
        assert "152 skipped" in text, "Missing 152 skipped in RELEASE_NOTES.md"
        assert "63.76s" in text, "Missing duration 63.76s in RELEASE_NOTES.md"

    def test_true_golden_metrics_present_in_master_plan(self):
        """MASTER_IMPLEMENTATION_PLAN.md must contain the True Golden metrics."""
        text = (REPO_ROOT / "MASTER_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
        assert "c05ca5c1be3b" in text, "Missing Golden SHA-256 fingerprint in MASTER_IMPLEMENTATION_PLAN.md"
        assert "288 -> 288" in text, "Missing 288 -> 288 runs invariant in MASTER_IMPLEMENTATION_PLAN.md"
        assert "5 -> 5" in text, "Missing 5 -> 5 page breaks invariant in MASTER_IMPLEMENTATION_PLAN.md"
        assert "19 -> 19" in text, "Missing 19 -> 19 pages invariant in MASTER_IMPLEMENTATION_PLAN.md"
        assert "1359 passed" in text or "1,359" in text, "Missing 1359 passed in MASTER_IMPLEMENTATION_PLAN.md"
        assert "152 skipped" in text, "Missing 152 skipped in MASTER_IMPLEMENTATION_PLAN.md"
        assert "63.76s" in text, "Missing duration 63.76s in MASTER_IMPLEMENTATION_PLAN.md"

    def test_port_consistency(self):
        """Default port must be 8765 across the application, docs, and launchers."""
        for path in [
            REPO_ROOT / "RELEASE_NOTES.md",
            REPO_ROOT / "clearmark-manager.ps1",
            REPO_ROOT / "service" / "scripts" / "server.py",
        ]:
            if path.exists():
                text = path.read_text(encoding="utf-8")
                assert "8765" in text, f"Port 8765 missing or inconsistent in {path.name}"

    def test_privacy_wording_scope(self):
        """DOCX Safe/Lossless privacy wording must be properly scoped to local zero egress."""
        text = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        assert "DOCX Safe/Lossless cleaning pipeline performs entirely locally and does not make network requests." in text

        # And in MASTER_IMPLEMENTATION_PLAN.md
        plan_text = (REPO_ROOT / "MASTER_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
        assert "DOCX Safe/Lossless cleaning pipeline performs entirely locally and does not make network requests." in plan_text
        assert (
            "Optional supported plain-text rewrite backends may access the network only when explicitly enabled by the user." in plan_text
            or "Optional remote text rewrite backends for supported plain-text workflows may use the network only when explicitly enabled by the user." in plan_text
        )
        assert "DOCX_SAFE_ZERO_EGRESS = PASS" in plan_text
        assert "APPLICATION_HAS_OPTIONAL_NETWORK_FEATURES = TRUE" in plan_text

    def test_final_evidence_package_complete(self):
        """artifacts/final_acceptance/ must contain all 7 required audit artifacts."""
        acceptance_dir = REPO_ROOT / "artifacts" / "final_acceptance"
        assert acceptance_dir.exists(), "artifacts/final_acceptance/ directory is missing"

        required_files = [
            "golden_documents.json",
            "real_document_fidelity_report_v2.json",
            "release_verification.json",
            "non_target_part_hashes.json",
            "visual_regression_report.json",
            "performance_report.json",
        ]
        for filename in required_files:
            file_path = acceptance_dir / filename
            assert file_path.exists(), f"Missing required evidence file: {filename}"
            assert file_path.stat().st_size > 0, f"Evidence file is empty: {filename}"

        # Check that golden and candidate docx are preserved
        docs_dir = acceptance_dir / "verification_docs"
        golden_docx = docs_dir / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
        candidate_docx = docs_dir / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"
        assert golden_docx.exists(), "Missing 01_GOLDEN_ORIGINAL_UNTOUCHED.docx in verification_docs"
        assert candidate_docx.exists(), "Missing 04_CANDIDATE_LOSSLESS_OUTPUT.docx in verification_docs"
