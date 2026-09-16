"""ClearMark v2.1 Batch Processing Engine.

Provides isolated, deterministic, failure-resilient batch processing across
multiple explicit files or directory trees.

Architectural Guarantees (Phase 4):
1. File-level failure isolation: one bad file never aborts the batch.
2. Deterministic execution order: preserves explicit arguments or sorts directory entries lexically.
3. Universal collision safety: outputs never overwrite originals or sibling batch results.
4. Mathematical reconciliation: sum of terminal item categories equals total input count.
5. Zero network egress during local deterministic batch processing.
6. Report privacy: no raw document body text in BatchReport or per-file JSON reports.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, Set, Tuple, Union

try:
    from .pipeline import Pipeline
    from .pipeline_types import (
        CleaningReport,
        ErrorCode,
        PipelineStatus,
        ProcessingMode,
    )
except (ImportError, ValueError):
    from pipeline import Pipeline
    from pipeline_types import (
        CleaningReport,
        ErrorCode,
        PipelineStatus,
        ProcessingMode,
    )

MAX_BATCH_FILES = int(os.environ.get("WATERMARKS_MAX_BATCH_FILES", "100"))
MAX_BATCH_TOTAL_BYTES = int(os.environ.get("WATERMARKS_MAX_BATCH_TOTAL_BYTES", str(200 * 1024 * 1024)))  # 200 MB
MAX_INPUT_BYTES = int(os.environ.get("WATERMARKS_MAX_FILE_BYTES", str(32 * 1024 * 1024)))  # 32 MB


class BatchLimitExceededError(ValueError):
    """Raised when root-level batch constraints are violated before processing."""
    pass


@dataclass
class BatchItemResult:
    """Per-file outcome within a batch execution."""
    index: int
    input_path: str
    input_sha256: Optional[str] = None
    format: str = "unknown"
    status: str = "INSPECTED"
    output_path: Optional[str] = None
    cleaned_bytes: Optional[bytes] = None
    report: Optional[dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message_safe: Optional[str] = None
    elapsed_ms: float = 0.0

    def to_dict(self, include_cleaned_data: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "index": self.index,
            "input_path": self.input_path,
            "input_sha256": self.input_sha256,
            "format": self.format,
            "status": self.status,
            "output_path": self.output_path,
            "error_code": self.error_code,
            "error_message_safe": self.error_message_safe,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "report": self.report,
        }
        if include_cleaned_data and self.cleaned_bytes is not None:
            d["cleaned"] = base64.b64encode(self.cleaned_bytes).decode("ascii")
        return d


@dataclass
class BatchSummary:
    """Terminal classification counts for an entire batch execution."""
    total: int = 0
    cleaned: int = 0
    no_change: int = 0
    inspected: int = 0
    unsupported: int = 0
    validation_failed: int = 0
    errors: int = 0
    skipped: int = 0

    def reconcile(self) -> bool:
        """Counts must mathematically reconcile: sum(terminal item categories) == total."""
        terminal_sum = (
            self.cleaned
            + self.no_change
            + self.inspected
            + self.unsupported
            + self.validation_failed
            + self.errors
            + self.skipped
        )
        return terminal_sum == self.total

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "cleaned": self.cleaned,
            "no_change": self.no_change,
            "inspected": self.inspected,
            "unsupported": self.unsupported,
            "validation_failed": self.validation_failed,
            "errors": self.errors,
            "skipped": self.skipped,
        }


@dataclass
class BatchReport:
    """Comprehensive, machine-readable report for a batch processing run."""
    batch_id: str
    started_at: str
    finished_at: str
    mode: str
    dry_run: bool
    input_count: int
    items: list[BatchItemResult]
    summary: BatchSummary
    privacy: dict[str, Any]
    performance_elapsed_ms: float
    schema_version: str = "2.1.0"
    operation: str = "clean"

    def to_dict(self, include_cleaned_data: bool = False) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "operation": self.operation,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_count": self.input_count,
            "summary": self.summary.to_dict(),
            "items": [item.to_dict(include_cleaned_data=include_cleaned_data) for item in self.items],
            "privacy": self.privacy,
            "performance": {
                "elapsed_ms": round(self.performance_elapsed_ms, 2),
            },
        }


def get_collision_safe_batch_path(
    base_dir: Path,
    rel_path: Optional[Path],
    filename: str,
    allocated_paths: Set[Path],
) -> Path:
    """Derive deterministic, collision-safe destination path preserving structure."""
    if rel_path is not None and len(rel_path.parts) > 1:
        target_dir = base_dir / rel_path.parent
    else:
        target_dir = base_dir

    os.makedirs(target_dir, exist_ok=True)

    src_p = Path(filename)
    stem = src_p.stem
    suffix = src_p.suffix

    candidate = target_dir / f"{stem}.cleaned{suffix}"
    idx = 1
    while candidate in allocated_paths or candidate.exists():
        candidate = target_dir / f"{stem}.cleaned.{idx}{suffix}"
        idx += 1

    allocated_paths.add(candidate)
    return candidate


def discover_input_files(
    inputs: list[Union[Path, str]],
    recursive: bool = False,
) -> list[Tuple[Path, Optional[Path]]]:
    """Safely discover files to process.

    Returns a list of tuples: (absolute_file_path, relative_path_if_directory).
    Explicit files preserve exact user ordering.
    Directory files are sorted by normalized relative path.
    Symlinks are not followed by default.
    """
    discovered: list[Tuple[Path, Optional[Path]]] = []

    for inp in inputs:
        p = Path(inp)
        # Check if symlink (reject following by default)
        if p.is_symlink():
            discovered.append((p, None))
            continue

        if not p.exists():
            # Keep non-existent explicit paths so item-level failure isolation can record them
            discovered.append((p, None))
            continue

        p_resolved = p.resolve()
        if p_resolved.is_file():
            discovered.append((p_resolved, None))
        elif p_resolved.is_dir():
            dir_files: list[Path] = []
            if recursive:
                for root, dirs, files in os.walk(p_resolved, followlinks=False):
                    root_path = Path(root)
                    for f in files:
                        fp = root_path / f
                        if not fp.is_symlink() and fp.is_file():
                            dir_files.append(fp)
            else:
                try:
                    for child in p_resolved.iterdir():
                        if not child.is_symlink() and child.is_file():
                            dir_files.append(child)
                except OSError:
                    pass

            # Stable lexical sort on normalized relative path
            dir_files.sort(key=lambda item: str(item.relative_to(p_resolved)).replace("\\", "/"))
            for df in dir_files:
                discovered.append((df, df.relative_to(p_resolved)))
        else:
            # Special file (socket, pipe, device)
            discovered.append((p, None))

    return discovered


class BatchProcessor:
    """Orchestrates batch inspection and cleaning with per-file fault isolation."""

    def __init__(
        self,
        pipeline: Optional[Pipeline] = None,
        max_batch_files: Optional[int] = None,
        max_batch_bytes: Optional[int] = None,
    ) -> None:
        self.pipeline = pipeline or Pipeline()
        self.max_batch_files = (
            max_batch_files
            if max_batch_files is not None
            else int(os.environ.get("WATERMARKS_MAX_BATCH_FILES", "100"))
        )
        self.max_batch_bytes = (
            max_batch_bytes
            if max_batch_bytes is not None
            else int(os.environ.get("WATERMARKS_MAX_BATCH_TOTAL_BYTES", str(200 * 1024 * 1024)))
        )

    def process_paths(
        self,
        inputs: list[Union[Path, str]],
        output_dir: Optional[Union[Path, str]] = None,
        reports_dir: Optional[Union[Path, str]] = None,
        mode: ProcessingMode = ProcessingMode.SAFE,
        dry_run: bool = False,
        recursive: bool = False,
        operation: str = "clean",
    ) -> BatchReport:
        """Execute batch over filesystem paths."""
        t_batch_start = time.perf_counter()
        batch_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        discovered = discover_input_files(inputs, recursive=recursive)

        if len(discovered) > self.max_batch_files:
            raise BatchLimitExceededError(
                f"Batch file count ({len(discovered)}) exceeds limit of {self.max_batch_files}"
            )

        # Preliminary total byte sum check on accessible files
        total_discovered_bytes = 0
        for fp, _ in discovered:
            if fp.is_file() and not fp.is_symlink():
                try:
                    total_discovered_bytes += fp.stat().st_size
                except OSError:
                    pass

        if total_discovered_bytes > self.max_batch_bytes:
            raise BatchLimitExceededError(
                f"Batch total bytes ({total_discovered_bytes}) exceeds limit of {self.max_batch_bytes}"
            )

        out_dir_path = Path(output_dir).resolve() if output_dir else None
        if out_dir_path:
            os.makedirs(out_dir_path, exist_ok=True)

        rep_dir_path = Path(reports_dir).resolve() if reports_dir else None
        if rep_dir_path:
            os.makedirs(rep_dir_path, exist_ok=True)

        allocated_paths: Set[Path] = set()
        items: list[BatchItemResult] = []
        summary = BatchSummary(total=len(discovered))

        for idx, (file_path, rel_path) in enumerate(discovered):
            t0 = time.perf_counter()
            display_path = str(file_path)

            # Per-file isolation: fresh state per item
            try:
                # 1. Check existence and basic safety
                if not file_path.exists():
                    item_res = BatchItemResult(
                        index=idx,
                        input_path=display_path,
                        format=file_path.suffix.lower().lstrip(".") or "unknown",
                        status="ERROR",
                        error_code="FILE_NOT_FOUND",
                        error_message_safe=f"File does not exist: {file_path}",
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                    )
                    summary.errors += 1
                    items.append(item_res)
                    continue

                if file_path.is_symlink():
                    item_res = BatchItemResult(
                        index=idx,
                        input_path=display_path,
                        format=file_path.suffix.lower().lstrip(".") or "unknown",
                        status="ERROR",
                        error_code="UNSUPPORTED_ARCHIVE_FEATURE",
                        error_message_safe="Symlinks are not followed for safety",
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                    )
                    summary.errors += 1
                    items.append(item_res)
                    continue

                if not file_path.is_file():
                    item_res = BatchItemResult(
                        index=idx,
                        input_path=display_path,
                        format="unknown",
                        status="ERROR",
                        error_code="INVALID_CONTAINER",
                        error_message_safe="Target is not a regular file",
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                    )
                    summary.errors += 1
                    items.append(item_res)
                    continue

                # 2. File size cap per file
                file_size = file_path.stat().st_size
                if file_size > MAX_INPUT_BYTES:
                    item_res = BatchItemResult(
                        index=idx,
                        input_path=display_path,
                        format=file_path.suffix.lower().lstrip(".") or "unknown",
                        status="ERROR",
                        error_code="PROCESSING_LIMIT_EXCEEDED",
                        error_message_safe=f"File exceeds maximum single-file size cap ({MAX_INPUT_BYTES} bytes)",
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                    )
                    summary.errors += 1
                    items.append(item_res)
                    continue

                # 3. Read bytes & compute SHA256
                raw_bytes = file_path.read_bytes()
                sha256 = hashlib.sha256(raw_bytes).hexdigest()

                # 4. Pipeline execution (clean or inspect)
                pipe = Pipeline()
                if operation == "inspect":
                    report = pipe.inspect(raw_bytes, filename=file_path.name, mode=mode)
                    cleaned_bytes = None
                else:
                    cleaned_bytes, report = pipe.clean(
                        raw_bytes,
                        filename=file_path.name,
                        mode=mode,
                        dry_run=dry_run,
                    )

                # 5. Determine terminal status and output path
                status_str = report.status.value
                dest_output_path: Optional[Path] = None

                if report.status in (PipelineStatus.CLEANED, PipelineStatus.NO_CHANGE_REQUIRED):
                    if report.status == PipelineStatus.CLEANED:
                        summary.cleaned += 1
                    else:
                        summary.no_change += 1

                    if not dry_run and cleaned_bytes is not None and report.output.changed:
                        # Write output file
                        if out_dir_path:
                            dest_output_path = get_collision_safe_batch_path(
                                out_dir_path, rel_path, file_path.name, allocated_paths
                            )
                        else:
                            dest_output_path = get_collision_safe_batch_path(
                                file_path.parent, None, file_path.name, allocated_paths
                            )
                        dest_output_path.write_bytes(cleaned_bytes)
                elif report.status == PipelineStatus.INSPECTED:
                    summary.inspected += 1
                elif report.status == PipelineStatus.UNSUPPORTED:
                    summary.unsupported += 1
                elif report.status == PipelineStatus.VALIDATION_FAILED:
                    summary.validation_failed += 1
                elif report.status == PipelineStatus.ERROR:
                    summary.errors += 1
                else:
                    summary.skipped += 1

                elapsed = (time.perf_counter() - t0) * 1000
                rep_dict = report.to_dict()

                item_res = BatchItemResult(
                    index=idx,
                    input_path=display_path,
                    input_sha256=sha256,
                    format=report.input.format,
                    status=status_str,
                    output_path=str(dest_output_path) if dest_output_path else None,
                    cleaned_bytes=cleaned_bytes,
                    report=rep_dict,
                    error_code=report.error_code.value if report.error_code else None,
                    error_message_safe=report.error_message,
                    elapsed_ms=elapsed,
                )
                items.append(item_res)

                # 6. Optional per-file report
                if rep_dir_path:
                    safe_stem = "".join(c for c in file_path.stem if c.isalnum() or c in ("-", "_")).strip() or "file"
                    report_file = rep_dir_path / f"{idx + 1:04d}-{safe_stem}.json"
                    report_file.write_text(json.dumps(rep_dict, indent=2), encoding="utf-8")

            except Exception as e:
                # File-level failure isolation: catch unexpected exceptions for this item
                summary.errors += 1
                items.append(
                    BatchItemResult(
                        index=idx,
                        input_path=display_path,
                        format=file_path.suffix.lower().lstrip(".") or "unknown",
                        status="ERROR",
                        error_code="INTERNAL_ERROR",
                        error_message_safe=f"Unexpected processing error: {e}",
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                    )
                )

        assert summary.reconcile(), "Batch summary counts failed mathematical reconciliation invariant"

        elapsed_total = (time.perf_counter() - t_batch_start) * 1000
        finished_at = datetime.now(timezone.utc).isoformat()

        batch_report = BatchReport(
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            mode=mode.value,
            dry_run=dry_run,
            input_count=len(discovered),
            items=items,
            summary=summary,
            privacy={"network_used": False, "external_services": []},
            performance_elapsed_ms=elapsed_total,
            operation=operation,
        )

        if rep_dir_path:
            batch_report_file = rep_dir_path / "batch_report.json"
            batch_report_file.write_text(json.dumps(batch_report.to_dict(), indent=2), encoding="utf-8")

        return batch_report

    def process_items(
        self,
        raw_items: list[dict[str, Any]],
        mode: ProcessingMode = ProcessingMode.SAFE,
        dry_run: bool = False,
        operation: str = "clean",
    ) -> BatchReport:
        """Process in-memory items (for HTTP API /batch)."""
        t_batch_start = time.perf_counter()
        batch_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        if len(raw_items) > self.max_batch_files:
            raise BatchLimitExceededError(
                f"Batch item count ({len(raw_items)}) exceeds limit of {self.max_batch_files}"
            )

        items: list[BatchItemResult] = []
        summary = BatchSummary(total=len(raw_items))
        total_bytes = 0

        for idx, entry in enumerate(raw_items):
            t0 = time.perf_counter()
            name = entry.get("name", f"item_{idx + 1}")

            try:
                # Extract data bytes
                if "data" in entry:
                    data = entry["data"]
                    if not isinstance(data, (bytes, bytearray)):
                        raise ValueError("Entry 'data' must be bytes")
                    data = bytes(data)
                elif "file" in entry:
                    b64_str = entry["file"]
                    if not isinstance(b64_str, str):
                        raise ValueError("Entry 'file' must be base64 string")
                    data = base64.b64decode(b64_str, validate=True)
                else:
                    raise ValueError("Entry missing 'data' or 'file' payload")

                total_bytes += len(data)
                if total_bytes > self.max_batch_bytes:
                    raise BatchLimitExceededError(
                        f"Cumulative batch payload exceeds {self.max_batch_bytes} bytes"
                    )

                if len(data) > MAX_INPUT_BYTES:
                    summary.errors += 1
                    items.append(
                        BatchItemResult(
                            index=idx,
                            input_path=name,
                            format=Path(name).suffix.lower().lstrip(".") or "unknown",
                            status="ERROR",
                            error_code="PROCESSING_LIMIT_EXCEEDED",
                            error_message_safe=f"Item exceeds maximum size cap ({MAX_INPUT_BYTES} bytes)",
                            elapsed_ms=(time.perf_counter() - t0) * 1000,
                        )
                    )
                    continue

                sha256 = hashlib.sha256(data).hexdigest()
                pipe = Pipeline()

                if operation == "inspect":
                    report = pipe.inspect(data, filename=name, mode=mode)
                    cleaned_bytes = None
                else:
                    cleaned_bytes, report = pipe.clean(data, filename=name, mode=mode, dry_run=dry_run)

                status_str = report.status.value
                if report.status == PipelineStatus.CLEANED:
                    summary.cleaned += 1
                elif report.status == PipelineStatus.NO_CHANGE_REQUIRED:
                    summary.no_change += 1
                elif report.status == PipelineStatus.INSPECTED:
                    summary.inspected += 1
                elif report.status == PipelineStatus.UNSUPPORTED:
                    summary.unsupported += 1
                elif report.status == PipelineStatus.VALIDATION_FAILED:
                    summary.validation_failed += 1
                elif report.status == PipelineStatus.ERROR:
                    summary.errors += 1
                else:
                    summary.skipped += 1

                elapsed = (time.perf_counter() - t0) * 1000
                items.append(
                    BatchItemResult(
                        index=idx,
                        input_path=name,
                        input_sha256=sha256,
                        format=report.input.format,
                        status=status_str,
                        output_path=None,
                        cleaned_bytes=cleaned_bytes,
                        report=report.to_dict(),
                        error_code=report.error_code.value if report.error_code else None,
                        error_message_safe=report.error_message,
                        elapsed_ms=elapsed,
                    )
                )

            except Exception as e:
                summary.errors += 1
                items.append(
                    BatchItemResult(
                        index=idx,
                        input_path=name,
                        format=Path(name).suffix.lower().lstrip(".") or "unknown",
                        status="ERROR",
                        error_code="INVALID_CONTAINER" if isinstance(e, ValueError) else "INTERNAL_ERROR",
                        error_message_safe=str(e),
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                    )
                )

        assert summary.reconcile(), "Batch summary counts failed mathematical reconciliation invariant"

        elapsed_total = (time.perf_counter() - t_batch_start) * 1000
        finished_at = datetime.now(timezone.utc).isoformat()

        return BatchReport(
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            mode=mode.value,
            dry_run=dry_run,
            input_count=len(raw_items),
            items=items,
            summary=summary,
            privacy={"network_used": False, "external_services": []},
            performance_elapsed_ms=elapsed_total,
            operation=operation,
        )
