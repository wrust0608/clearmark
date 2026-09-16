"""Tests for Phase 4: Batch Processing Engine (service/scripts/batch_processor.py).

Covers:
- Fault isolation: one bad file never aborts the batch (mixed valid, corrupt, unsupported)
- Deterministic ordering: explicit arguments order preserved, directory lexical sort
- Output collision safety: same basename across directories, duplicate inputs, existing files
- Failed item invariant: no output file written for failed/unsupported items
- Dry-run invariant: zero outputs written, would_change reflects plan
- Mathematical reconciliation: sum(terminal categories) == total
- Cross-file state isolation: item B never inherits findings/warnings/error state from item A
- Safety boundaries: MAX_BATCH_FILES, MAX_BATCH_TOTAL_BYTES, symlinks ignored
- Report privacy: no raw document body text in BatchReport
- Zero network socket activity
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from service.scripts.batch_processor import (
    BatchLimitExceededError,
    BatchProcessor,
    BatchReport,
    BatchSummary,
    discover_input_files,
    get_collision_safe_batch_path,
)
from service.scripts.pipeline_types import ProcessingMode

GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"


# 1. Fault Isolation: Mixed valid, corrupt, and unsupported
def test_batch_fault_isolation(tmp_path: Path):
    valid_docx = tmp_path / "valid.docx"
    valid_docx.write_bytes(GOLDEN_DOCX.read_bytes())

    corrupt_docx = tmp_path / "corrupt.docx"
    corrupt_docx.write_bytes(b"PK\x03\x04corrupted_payload_data")

    unsupported_file = tmp_path / "unsupported.xyz"
    unsupported_file.write_bytes(b"some unknown format bytes")

    valid_txt = tmp_path / "valid.txt"
    valid_txt.write_text("Clean text without watermarks.", encoding="utf-8")

    out_dir = tmp_path / "cleaned_out"

    processor = BatchProcessor()
    report = processor.process_paths(
        inputs=[valid_docx, corrupt_docx, unsupported_file, valid_txt],
        output_dir=out_dir,
    )

    assert report.input_count == 4
    assert len(report.items) == 4

    # Mathematical reconciliation invariant
    assert report.summary.reconcile()
    assert report.summary.total == 4

    # Item 1: valid docx -> CLEANED
    item1 = report.items[0]
    assert item1.status == "CLEANED"
    assert item1.output_path is not None
    assert Path(item1.output_path).exists()

    # Item 2: corrupt docx -> ERROR / INVALID_CONTAINER
    item2 = report.items[1]
    assert item2.status == "ERROR"
    assert item2.error_code in ("INVALID_CONTAINER", "INTERNAL_ERROR")
    assert item2.output_path is None

    # Item 3: unsupported -> UNSUPPORTED
    item3 = report.items[2]
    assert item3.status == "UNSUPPORTED"
    assert item3.output_path is None

    # Item 4: valid txt -> NO_CHANGE_REQUIRED (no watermarks)
    item4 = report.items[3]
    assert item4.status == "NO_CHANGE_REQUIRED"

    # Crucial fault isolation proof: failure of item 2 did NOT stop item 3 or 4
    assert report.summary.cleaned == 1
    assert report.summary.errors == 1
    assert report.summary.unsupported == 1
    assert report.summary.no_change == 1


# 2. Deterministic Ordering
def test_batch_deterministic_ordering(tmp_path: Path):
    f_c = tmp_path / "c.txt"
    f_a = tmp_path / "a.txt"
    f_b = tmp_path / "b.txt"
    for f in (f_c, f_a, f_b):
        f.write_text("test", encoding="utf-8")

    # Explicit order: c, a, b must be preserved
    discovered_explicit = discover_input_files([f_c, f_a, f_b])
    paths_explicit = [p.name for p, _ in discovered_explicit]
    assert paths_explicit == ["c.txt", "a.txt", "b.txt"]

    # Directory discovery must be lexically sorted: a, b, c
    discovered_dir = discover_input_files([tmp_path])
    paths_dir = [p.name for p, _ in discovered_dir]
    assert paths_dir == ["a.txt", "b.txt", "c.txt"]


# 3. Output Collision Safety across directories and duplicate inputs
def test_batch_output_collision_safety(tmp_path: Path):
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()

    # Same filename in different directories
    f1 = dir1 / "document.docx"
    f2 = dir2 / "document.docx"
    f1.write_bytes(GOLDEN_DOCX.read_bytes())
    f2.write_bytes(GOLDEN_DOCX.read_bytes())

    out_dir = tmp_path / "out"

    processor = BatchProcessor()
    # Also pass f1 twice to test duplicate explicit arguments
    report = processor.process_paths(
        inputs=[f1, f2, f1],
        output_dir=out_dir,
    )

    assert report.summary.cleaned == 3
    outputs = [item.output_path for item in report.items]
    # Every output must be distinct
    assert len(set(outputs)) == 3
    for op in outputs:
        assert op is not None
        assert Path(op).exists()
        # Original must not be overwritten
        assert Path(op) != f1
        assert Path(op) != f2


# 4. Existing Output is not overwritten
def test_batch_existing_output_not_overwritten(tmp_path: Path):
    doc = tmp_path / "report.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Pre-existing file at default output target
    pre_existing = out_dir / "report.cleaned.docx"
    pre_existing.write_text("PRE_EXISTING_CONTENT", encoding="utf-8")

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[doc], output_dir=out_dir)

    assert report.summary.cleaned == 1
    # Pre-existing file untouched
    assert pre_existing.read_text(encoding="utf-8") == "PRE_EXISTING_CONTENT"
    # New output allocated collision suffix
    new_out = Path(report.items[0].output_path)
    assert new_out != pre_existing
    assert new_out.name == "report.cleaned.1.docx"
    assert new_out.exists()


# 5. Failed Items Write Zero Output Files
def test_batch_failed_items_write_zero_outputs(tmp_path: Path):
    corrupt = tmp_path / "bad.docx"
    corrupt.write_bytes(b"PK\x03\x04broken")
    out_dir = tmp_path / "out"

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[corrupt], output_dir=out_dir)

    assert report.summary.errors == 1
    assert report.items[0].output_path is None
    # Output directory must remain empty of final files
    cleaned_files = list(out_dir.glob("*.cleaned*")) if out_dir.exists() else []
    assert len(cleaned_files) == 0


# 6. Dry-Run Invariant: Zero Outputs Written, would_change Tracked
def test_batch_dry_run_zero_outputs(tmp_path: Path):
    doc = tmp_path / "input.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())
    out_dir = tmp_path / "out"

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[doc], output_dir=out_dir, dry_run=True)

    assert report.dry_run is True
    assert report.summary.inspected == 1
    assert report.summary.cleaned == 0
    assert report.items[0].output_path is None
    assert report.items[0].report["output"]["changed"] is False
    assert report.items[0].report["output"]["would_change"] is True

    # Zero files written to out_dir
    cleaned_files = list(out_dir.glob("*")) if out_dir.exists() else []
    assert len(cleaned_files) == 0


# 7. Cross-File State Isolation (Section 29)
def test_batch_cross_file_state_isolation(tmp_path: Path):
    doc1 = tmp_path / "with_metadata.docx"
    doc1.write_bytes(GOLDEN_DOCX.read_bytes())

    doc2 = tmp_path / "clean.txt"
    doc2.write_text("No watermark here.", encoding="utf-8")

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[doc1, doc2])

    assert len(report.items) == 2
    item1 = report.items[0]
    item2 = report.items[1]

    # Item 1 had DOCX metadata findings
    assert len(item1.report["inspection"]["findings"]) > 0
    assert len(item1.report["mutation_plan"]["mutations"]) > 0

    # Item 2 MUST NOT inherit findings or mutations from Item 1
    assert len(item2.report["inspection"]["findings"]) == 0
    assert len(item2.report["mutation_plan"]["mutations"]) == 0
    assert item2.report["input"]["format"] == "txt"


# 8. Per-File Reports Directory (Section 13)
def test_batch_per_file_reports_generation(tmp_path: Path):
    doc = tmp_path / "document.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())
    rep_dir = tmp_path / "reports"

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[doc], reports_dir=rep_dir)

    assert rep_dir.exists()
    batch_json = rep_dir / "batch_report.json"
    assert batch_json.exists()
    batch_data = json.loads(batch_json.read_text(encoding="utf-8"))
    assert batch_data["summary"]["cleaned"] == 1

    item_json = rep_dir / "0001-document.json"
    assert item_json.exists()
    item_data = json.loads(item_json.read_text(encoding="utf-8"))
    assert item_data["input"]["format"] == "docx"


# 9. Safety Boundaries: MAX_BATCH_FILES Exceeded
def test_batch_max_files_limit(tmp_path: Path):
    files = []
    for i in range(5):
        f = tmp_path / f"file_{i}.txt"
        f.write_text("text", encoding="utf-8")
        files.append(f)

    processor = BatchProcessor(max_batch_files=3)
    with pytest.raises(BatchLimitExceededError) as exc_info:
        processor.process_paths(inputs=files)
    assert "exceeds limit" in str(exc_info.value)


# 10. Zero Network Invariant (Section 28)
def test_batch_zero_network(tmp_path: Path, monkeypatch):
    def _forbidden_connect(*args, **kwargs):
        raise AssertionError("CRITICAL: Network attempt during local batch processing!")

    monkeypatch.setattr(socket, "socket", _forbidden_connect)
    monkeypatch.setattr(socket, "create_connection", _forbidden_connect)

    doc = tmp_path / "test.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[doc], dry_run=True)
    assert report.summary.inspected == 1
    assert report.privacy["network_used"] is False


# 11. Report Privacy Invariant (Section 27)
def test_batch_report_privacy(tmp_path: Path):
    txt = tmp_path / "secret.txt"
    secret_token = "TOP_SECRET_PASSPHRASE_XYZ987"
    txt.write_text(f"Document content containing {secret_token}\u200Bhidden", encoding="utf-8")

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[txt])

    report_str = json.dumps(report.to_dict())
    assert secret_token not in report_str


# 12. Safety Boundaries: MAX_BATCH_TOTAL_BYTES Exceeded
def test_batch_max_bytes_limit(tmp_path: Path):
    f1 = tmp_path / "big_1.txt"
    f2 = tmp_path / "big_2.txt"
    f1.write_bytes(b"A" * 1000)
    f2.write_bytes(b"B" * 1000)

    processor = BatchProcessor(max_batch_bytes=1500)
    with pytest.raises(BatchLimitExceededError) as exc_info:
        processor.process_paths(inputs=[f1, f2])
    assert "exceeds limit" in str(exc_info.value)


# 13. Symlink Handling: Not Followed by Default
def test_batch_symlink_safety(tmp_path: Path, monkeypatch):
    target_file = tmp_path / "target.docx"
    target_file.write_bytes(GOLDEN_DOCX.read_bytes())
    link_file = tmp_path / "link.docx"

    try:
        link_file.symlink_to(target_file)
    except (OSError, NotImplementedError):
        # On Windows without Developer Mode, monkeypatch is_symlink
        link_file.write_bytes(GOLDEN_DOCX.read_bytes())
        orig_is_symlink = Path.is_symlink
        def _mock_is_symlink(self):
            if self.name == "link.docx":
                return True
            return orig_is_symlink(self)
        monkeypatch.setattr(Path, "is_symlink", _mock_is_symlink)

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[link_file])
    assert report.summary.errors == 1
    assert report.items[0].status == "ERROR"
    assert "symlink" in report.items[0].error_message_safe.lower()


# 14. Directory Traversal Safety: Relative Path Containment
def test_batch_directory_traversal_safety(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    f1 = input_dir / "doc1.txt"
    f1.write_text("Hello", encoding="utf-8")

    out_dir = tmp_path / "out"
    processor = BatchProcessor()
    report = processor.process_paths(inputs=[input_dir], output_dir=out_dir)

    assert report.summary.no_change == 1
    # Verify outputs stay within out_dir
    if report.items[0].output_path:
        out_p = Path(report.items[0].output_path).resolve()
        assert out_dir.resolve() in out_p.parents


# 15. Canonical BatchReport Strictly Excludes Cleaned Payloads
def test_batch_report_excludes_cleaned_payload(tmp_path: Path):
    doc = tmp_path / "sample.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())

    processor = BatchProcessor()
    report = processor.process_paths(inputs=[doc])

    assert report.summary.cleaned == 1
    # Transient item has cleaned_bytes in memory
    assert report.items[0].cleaned_bytes is not None

    # Canonical report dictionary MUST NOT contain cleaned_bytes or base64
    rep_dict = report.to_dict()
    item_dict = rep_dict["items"][0]
    assert "cleaned" not in item_dict
    assert "cleaned_bytes" not in item_dict
    assert "content_base64" not in item_dict

    # Serialized JSON size must be compact metadata only
    json_bytes = json.dumps(rep_dict).encode("utf-8")
    assert len(json_bytes) < 10000  # Metadata report is small, not embedding 50KB+ DOCX payload


# 16. Reports Directory Files Exclude Cleaned Payloads
def test_batch_reports_dir_excludes_cleaned_payload(tmp_path: Path):
    doc = tmp_path / "sample.docx"
    doc.write_bytes(GOLDEN_DOCX.read_bytes())
    rep_dir = tmp_path / "reports_out"

    processor = BatchProcessor()
    processor.process_paths(inputs=[doc], reports_dir=rep_dir)

    batch_json = rep_dir / "batch_report.json"
    assert batch_json.exists()
    batch_raw = batch_json.read_text(encoding="utf-8")
    assert "cleaned_bytes" not in batch_raw
    assert "content_base64" not in batch_raw

    item_json = rep_dir / "0001-sample.json"
    assert item_json.exists()
    item_raw = item_json.read_text(encoding="utf-8")
    assert "cleaned_bytes" not in item_raw
    assert "content_base64" not in item_raw

