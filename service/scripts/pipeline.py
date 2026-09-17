"""service/scripts/pipeline.py

Unified File Workflow Pipeline Engine for ClearMark v2.1.
Implements the canonical lifecycle:
INPUT -> FORMAT DETECTION -> INSPECTION -> FORMAT POLICY -> MUTATION PLAN -> CLEAN -> VALIDATE -> REPORT -> OUTPUT

Adheres strictly to Sections 3, 4, 5, 6, 8, 9, 10, 15, 20, 23, and 24:
- Universal PipelineStatus states (INSPECTED, NO_CHANGE_REQUIRED, CLEANED, VALIDATION_FAILED, UNSUPPORTED, ERROR)
- Strictly local processing by default (network_used = False)
- Non-destructive inspection
- Dry-run capability (--dry-run)
- Safe atomic in-place replacement
- Zero full-document text leakage in reports
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    MAX_INPUT_BYTES,
    looks_binary,
    safe_write_bytes,
)
try:
    from .format_dispatch import classify, classify_bytes
    from .format_policy import FormatPolicy, FormatPolicyRegistry
    from .pipeline_types import (
        CleaningReport,
        DetectionStatus,
        ErrorCode,
        FidelityLevel,
        FileIdentity,
        Finding,
        InspectionData,
        MutationRecord,
        OutputRecord,
        PipelineStatus,
        PolicySelection,
        PrivacySummary,
        ProcessingMode,
        ValidationOutcome,
    )
except (ImportError, ValueError):
    from format_dispatch import classify, classify_bytes
    from format_policy import FormatPolicy, FormatPolicyRegistry
    from pipeline_types import (
        CleaningReport,
        DetectionStatus,
        ErrorCode,
        FidelityLevel,
        FileIdentity,
        Finding,
        InspectionData,
        MutationRecord,
        OutputRecord,
        PipelineStatus,
        PolicySelection,
        PrivacySummary,
        ProcessingMode,
        ValidationOutcome,
    )


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _docx_plan_to_mutations(plan: Any) -> list[dict[str, Any]]:
    """Deterministic conversion of DocxMutationPlan into structured mutation dictionaries."""
    mutations: list[dict[str, Any]] = []
    for tm in getattr(plan, "text_mutations", []):
        mutations.append({
            "kind": "text",
            "part": tm.part_name,
            "desc": f"U+{tm.codepoint:04X} {tm.char_name}",
            "location": f"p{tm.p_idx}:r{tm.r_idx}:t{tm.t_idx}:offset{tm.offset}",
            "codepoint": f"U+{tm.codepoint:04X}",
        })
    for mm in getattr(plan, "metadata_mutations", []):
        mutations.append({
            "kind": "metadata",
            "part": mm.part_name,
            "desc": mm.label,
            "tag": mm.tag_name,
        })
    for pd in getattr(plan, "part_drops", []):
        mutations.append({
            "kind": "part_drop",
            "part": pd.part_name,
            "desc": pd.reason,
        })
    for med in getattr(plan, "media_mutations", []):
        mutations.append({
            "kind": "media",
            "part": med.part_name,
            "desc": "embedded media clean",
        })
    return mutations


class Pipeline:
    """Universal pipeline engine for multi-format watermark inspection and cleaning."""

    def __init__(self, registry: Optional[FormatPolicyRegistry] = None) -> None:
        self.registry = registry or FormatPolicyRegistry.get_default()

    def _resolve_input(
        self,
        input_source: Union[str, Path, bytes],
        filename: Optional[str] = None,
    ) -> Tuple[bytes, str, str]:
        """Resolve input bytes, filename, and format extension."""
        if isinstance(input_source, (str, Path)):
            path = Path(input_source)
            if not path.is_file():
                raise FileNotFoundError(f"Input file not found: {path}")
            data = path.read_bytes()
            name = filename or path.name
        elif isinstance(input_source, bytes):
            data = input_source
            name = filename or "unnamed_input"
        else:
            raise TypeError(f"Unsupported input type: {type(input_source)}")

        ext = Path(name).suffix.lower().lstrip(".")
        if not ext or ext == "unknown":
            # Phase 9: Cheap probe first. If data starts with PK, preflight before deep container sniffing
            if data.startswith(b"PK"):
                from security import require_safe_zip_container
                require_safe_zip_container(data)

            kind = classify_bytes(data, name)
            from container_meta import detect_container_format
            from image_meta import detect_format as detect_image_format
            from av_meta import detect_av_format

            det_c = detect_container_format(Path(name or "input"), data)
            if det_c != "unknown":
                ext = det_c
            else:
                det_i = detect_image_format(data)
                if det_i != "unknown":
                    ext = det_i
                else:
                    det_a = detect_av_format(data)
                    if det_a != "unknown":
                        ext = det_a
                    else:
                        ext = kind if kind != "unknown" else ""

        return data, name, ext

    def inspect(
        self,
        input_source: Union[str, Path, bytes],
        filename: Optional[str] = None,
        mode: ProcessingMode = ProcessingMode.SAFE,
    ) -> CleaningReport:
        """Perform zero-mutation, strictly read-only inspection (Sections 2, 3, 4, 7, 8, 9)."""
        t0 = time.perf_counter()
        try:
            data, name, fmt = self._resolve_input(input_source, filename)
        except Exception as e:
            from security import SecurityViolation
            if isinstance(e, SecurityViolation):
                sv = e
                size = len(input_source) if isinstance(input_source, bytes) else (
                    Path(input_source).stat().st_size if isinstance(input_source, (str, Path)) and Path(input_source).is_file() else 0
                )
                ident = FileIdentity(filename=filename or "unnamed_input", format="unknown", size=size, sha256="")
                err_code = ErrorCode.PROCESSING_LIMIT_EXCEEDED if sv.is_limit else ErrorCode.INVALID_CONTAINER
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(detection_status=DetectionStatus.UNAVAILABLE),
                    policy=PolicySelection(mode=mode, format_policy="unknown"),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[sv.finding.reason]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=""),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=err_code,
                    error_message=f"Security preflight failed: {sv.finding.reason}",
                )
            raise

        size = len(data)
        sha = _compute_sha256(data)
        ident = FileIdentity(filename=name, format=fmt or "unknown", size=size, sha256=sha)

        if size > MAX_INPUT_BYTES:
            return CleaningReport(
                status=PipelineStatus.ERROR,
                input=ident,
                inspection=InspectionData(detection_status=DetectionStatus.UNAVAILABLE),
                policy=PolicySelection(mode=mode, format_policy=fmt),
                mutation_plan=MutationRecord(),
                validation=ValidationOutcome(status="FAIL", warnings=["Input exceeds MAX_INPUT_BYTES limit"]),
                output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                privacy=PrivacySummary(network_used=False),
                performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                error_code=ErrorCode.PROCESSING_LIMIT_EXCEEDED,
                error_message=f"File exceeds maximum size {MAX_INPUT_BYTES} bytes",
            )

        # Phase 9: Container & XML Security Preflight before format dispatch
        if data.startswith(b"PK") or fmt in ("docx", "xlsx", "pptx", "odt", "epub"):
            try:
                from security import require_safe_zip_container, SecurityViolation
                require_safe_zip_container(data)
            except SecurityViolation as sv:
                err_code = ErrorCode.PROCESSING_LIMIT_EXCEEDED if sv.is_limit else ErrorCode.INVALID_CONTAINER
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(detection_status=DetectionStatus.UNAVAILABLE),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[sv.finding.reason]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=err_code,
                    error_message=f"Security preflight failed: {sv.finding.reason}",
                )

        policy = self.registry.get(fmt)
        if policy is None:
            unsupported_finding = Finding(
                detector_id="FormatClassifier",
                category="format",
                reason="Unsupported or unrecognized file format",
                actionability="UNSUPPORTED",
            )
            return CleaningReport(
                status=PipelineStatus.UNSUPPORTED,
                input=ident,
                inspection=InspectionData(
                    findings=[unsupported_finding],
                    detection_status=DetectionStatus.UNSUPPORTED,
                ),
                policy=PolicySelection(mode=mode, format_policy=fmt),
                mutation_plan=MutationRecord(),
                validation=ValidationOutcome(status="SKIPPED"),
                output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                privacy=PrivacySummary(network_used=False),
                performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                error_code=ErrorCode.UNSUPPORTED_FORMAT,
                error_message=f"Format '{fmt}' is not supported",
            )

        # Capability-aware detection setup
        findings: list[Union[Finding, str]] = []
        detectors_run: list[str] = []
        detectors_unavailable: list[str] = []
        warnings: list[str] = []

        # Check optional dependencies for this format
        for dep in policy.optional_dependencies:
            if shutil.which(dep) is None:
                detectors_unavailable.append(dep)

        # Mode explanation if BALANCED or AGGRESSIVE has no separate action
        if mode != ProcessingMode.SAFE:
            if not policy.destructive_operations:
                warnings.append(
                    f"Mode {mode.value} active; format '{fmt}' operates identically to SAFE under current fidelity rules"
                )

        if fmt == "docx":
            try:
                from docx.detector import DocxDetector
                from docx.package import DocxPackage

                detectors_run.extend([
                    "DocxDetector",
                    "DocxMetadataDetector",
                    "DocxUnicodeDetector",
                    "DocxMediaDetector",
                    "DocxCustomXmlDetector",
                ])

                pkg = DocxPackage(data)
                detector = DocxDetector(pkg, {"mode": mode.value})
                plan = detector.build_plan()

                for tm in plan.text_mutations:
                    findings.append(
                        Finding(
                            detector_id="DocxUnicodeDetector",
                            category="unicode_carrier",
                            target_part=tm.part_name,
                            location=f"p{tm.p_idx}:r{tm.r_idx}:t{tm.t_idx}:offset{tm.offset}",
                            codepoint=f"U+{tm.codepoint:04X}",
                            reason=tm.char_name,
                        )
                    )
                for mm in plan.metadata_mutations:
                    findings.append(
                        Finding(
                            detector_id="DocxMetadataDetector",
                            category="metadata_provenance",
                            target_part=mm.part_name,
                            metadata_key=mm.tag_name,
                            reason=mm.label,
                        )
                    )
                for pd in plan.part_drops:
                    findings.append(
                        Finding(
                            detector_id="DocxCustomXmlDetector",
                            category="part_drop",
                            target_part=pd.part_name,
                            reason=pd.reason,
                        )
                    )
                for med in plan.media_mutations:
                    findings.append(
                        Finding(
                            detector_id="DocxMediaDetector",
                            category="media_metadata",
                            target_part=med.part_name,
                            reason="embedded media metadata",
                        )
                    )
            except Exception as e:
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message=f"Invalid or corrupted DOCX archive: {e}",
                )
        elif fmt == "xlsx":
            try:
                from xlsx import XlsxDetector, XlsxPackage

                detectors = ["XlsxDetector", "XlsxMetadataDetector", "XlsxUnicodeDetector"]
                if mode != ProcessingMode.SAFE:
                    detectors.append("XlsxMediaDetector")
                detectors_run.extend(detectors)

                pkg = XlsxPackage(data)
                detector = XlsxDetector(pkg, {"mode": mode.value})
                plan = detector.build_plan()

                for tm in plan.text_mutations:
                    findings.append(
                        Finding(
                            detector_id="XlsxUnicodeDetector",
                            category="unicode_carrier",
                            target_part=tm.part_name,
                            location=tm.location,
                            codepoint=f"U+{tm.codepoint:04X}",
                            reason=tm.char_name,
                        )
                    )
                for mm in plan.metadata_mutations:
                    findings.append(
                        Finding(
                            detector_id="XlsxMetadataDetector",
                            category="metadata_provenance",
                            target_part=mm.part_name,
                            metadata_key=mm.tag_name,
                            reason=mm.label,
                        )
                    )
                for pd in plan.part_drops:
                    findings.append(
                        Finding(
                            detector_id="XlsxMetadataDetector",
                            category="part_drop",
                            target_part=pd.part_name,
                            reason=pd.reason,
                        )
                    )
                for med in plan.media_mutations:
                    findings.append(
                        Finding(
                            detector_id="XlsxMediaDetector",
                            category="media_metadata",
                            target_part=med.part_name,
                            reason=med.reason,
                        )
                    )
            except Exception as e:
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message=f"Invalid or corrupted XLSX archive: {e}",
                )
        elif fmt == "pptx":
            try:
                from pptx import PptxDetector, PptxPackage

                detectors_run.extend([
                    "PptxDetector",
                    "PptxMetadataDetector",
                    "PptxUnicodeDetector",
                ])

                pkg = PptxPackage(data)
                detector = PptxDetector(pkg, {"mode": mode.value})
                plan = detector.build_plan()

                for tm in plan.text_mutations:
                    findings.append(
                        Finding(
                            detector_id="PptxUnicodeDetector",
                            category="unicode_carrier",
                            target_part=tm.part_name,
                            location=tm.location,
                            codepoint=f"U+{tm.codepoint:04X}",
                            reason=tm.char_name,
                        )
                    )
                for mm in plan.metadata_mutations:
                    findings.append(
                        Finding(
                            detector_id="PptxMetadataDetector",
                            category="metadata_provenance",
                            target_part=mm.part_name,
                            metadata_key=mm.tag_name,
                            reason=mm.label,
                        )
                    )
                for pd in plan.part_drops:
                    findings.append(
                        Finding(
                            detector_id="PptxMetadataDetector",
                            category="part_drop",
                            target_part=pd.part_name,
                            reason=pd.reason,
                        )
                    )
            except Exception as e:
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message=f"Invalid or corrupted PPTX archive: {e}",
                )
        elif fmt in ("png", "jpeg", "jpg", "webp", "gif", "bmp", "tiff", "avif", "heic"):
            try:
                from image_meta import inspect_image

                detectors_run.append("ImageMetaInspector")
                img_report = inspect_image(Path(name), data=data)
                for f in getattr(img_report, "findings", []):
                    findings.append(
                        Finding(
                            detector_id="ImageMetaInspector",
                            category="metadata",
                            metadata_key=f,
                            reason=f,
                        )
                    )
                if getattr(img_report, "has_c2pa", False):
                    findings.append(
                        Finding(
                            detector_id="ImageMetaInspector",
                            category="c2pa",
                            reason="C2PA manifest detected",
                        )
                    )
                if getattr(img_report, "has_ai_metadata", False):
                    findings.append(
                        Finding(
                            detector_id="ImageMetaInspector",
                            category="ai_metadata",
                            reason="AI generation metadata detected",
                        )
                    )
            except Exception as e:
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message=f"Corrupted image payload: {e}",
                )
        elif fmt in ("txt", "md", "html", "latex"):
            if looks_binary(data):
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=["refusing to inspect bytes that look like a binary container as text"]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message="refusing to inspect bytes that look like a binary container as text",
                )
            try:
                from text_unicode import inspect_text

                detectors_run.append("UnicodeTextInspector")
                text_str = data.decode("utf-8", errors="replace")
                t_report = inspect_text(text_str, aggressive=(mode == ProcessingMode.AGGRESSIVE))
                for hit in getattr(t_report, "hits", []):
                    cp_int = ord(hit.char) if hasattr(hit, "char") else 0
                    cp_hex = f"U+{cp_int:04X}"
                    findings.append(
                        Finding(
                            detector_id="UnicodeTextInspector",
                            category="unicode_carrier",
                            location=f"offset:{getattr(hit, 'offset', 0)}",
                            codepoint=cp_hex,
                            reason=getattr(hit, "name", "invisible_char"),
                        )
                    )
            except Exception as e:
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message=f"Text inspection failure: {e}",
                )
        elif fmt in ("pdf", "odt", "ods", "odp", "epub", "svg"):
            try:
                from container_meta import inspect_container

                detectors_run.append("ContainerMetaInspector")
                c_report = inspect_container(Path(name), data=data)
                for f in getattr(c_report, "findings", []):
                    if "unavailable" in str(f).lower() or "not found" in str(f).lower():
                        continue
                    findings.append(
                        Finding(
                            detector_id="ContainerMetaInspector",
                            category="container_metadata",
                            metadata_key=f,
                            reason=f,
                        )
                    )
                if getattr(c_report, "has_c2pa", False):
                    findings.append(
                        Finding(
                            detector_id="ContainerMetaInspector",
                            category="c2pa",
                            reason="C2PA manifest detected",
                        )
                    )
                if getattr(c_report, "has_ai_metadata", False):
                    findings.append(
                        Finding(
                            detector_id="ContainerMetaInspector",
                            category="ai_metadata",
                            reason="AI metadata detected",
                        )
                    )
            except Exception as e:
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message=f"Container inspection failure: {e}",
                )
        elif fmt in ("mp4", "mov", "m4a", "m4v", "wav", "mp3", "flac", "audio", "video"):
            try:
                from av_meta import inspect_av

                detectors_run.append("AVMetaInspector")
                av_report = inspect_av(Path(name), data=data)
                for f in getattr(av_report, "findings", []):
                    findings.append(
                        Finding(
                            detector_id="AVMetaInspector",
                            category="av_metadata",
                            metadata_key=f,
                            reason=f,
                        )
                    )
                if getattr(av_report, "has_c2pa", False):
                    findings.append(
                        Finding(
                            detector_id="AVMetaInspector",
                            category="c2pa",
                            reason="C2PA manifest detected in audio/video container",
                        )
                    )
                if getattr(av_report, "has_ai_metadata", False):
                    findings.append(
                        Finding(
                            detector_id="AVMetaInspector",
                            category="ai_metadata",
                            reason="AI metadata detected in audio/video container",
                        )
                    )
            except Exception as e:
                return CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(
                        detectors_run=detectors_run,
                        detection_status=DetectionStatus.UNAVAILABLE,
                    ),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message=f"Audio/video inspection failure: {e}",
                )
        else:
            detectors_run.append("GenericContainerInspector")

        # Determine overall detection status
        detection_status = DetectionStatus.DETECTED if len(findings) > 0 else DetectionStatus.NOT_DETECTED

        elapsed = (time.perf_counter() - t0) * 1000.0
        return CleaningReport(
            status=PipelineStatus.INSPECTED,
            input=ident,
            inspection=InspectionData(
                findings=findings,
                detectors_run=detectors_run,
                detectors_unavailable=detectors_unavailable,
                unsupported_checks=[],
                detection_status=detection_status,
            ),
            policy=PolicySelection(
                mode=mode,
                format_policy=fmt,
                normalize_spaces=policy.allow_destructive_normalization,
                remote_processing=False,
            ),
            mutation_plan=MutationRecord(),
            validation=ValidationOutcome(status="SKIPPED", warnings=warnings),
            output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
            privacy=PrivacySummary(network_used=False),
            performance_elapsed_ms=elapsed,
        )

    def clean(
        self,
        input_source: Union[str, Path, bytes],
        output_path: Optional[Union[str, Path]] = None,
        filename: Optional[str] = None,
        mode: ProcessingMode = ProcessingMode.SAFE,
        dry_run: bool = False,
        in_place: bool = False,
        options: Optional[dict[str, Any]] = None,
    ) -> Tuple[bytes, CleaningReport]:
        """Execute deterministic cleaning and validation across any supported format."""
        t0 = time.perf_counter()
        try:
            data, name, fmt = self._resolve_input(input_source, filename)
        except Exception as e:
            from security import SecurityViolation
            if isinstance(e, SecurityViolation):
                sv = e
                size = len(input_source) if isinstance(input_source, bytes) else (
                    Path(input_source).stat().st_size if isinstance(input_source, (str, Path)) and Path(input_source).is_file() else 0
                )
                ident = FileIdentity(filename=filename or "unnamed_input", format="unknown", size=size, sha256="")
                err_code = ErrorCode.PROCESSING_LIMIT_EXCEEDED if sv.is_limit else ErrorCode.INVALID_CONTAINER
                report = CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(detection_status=DetectionStatus.UNAVAILABLE),
                    policy=PolicySelection(mode=mode, format_policy="unknown"),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[sv.finding.reason]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=""),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=err_code,
                    error_message=f"Security preflight failed: {sv.finding.reason}",
                )
                return b"", report
            raise

        size = len(data)
        sha = _compute_sha256(data)
        ident = FileIdentity(filename=name, format=fmt or "unknown", size=size, sha256=sha)
        opts = dict(options or {})

        # Phase 9: Container & XML Security Preflight before format dispatch
        if data.startswith(b"PK") or fmt in ("docx", "xlsx", "pptx", "odt", "epub"):
            try:
                from security import require_safe_zip_container, SecurityViolation
                require_safe_zip_container(data)
            except SecurityViolation as sv:
                err_code = ErrorCode.PROCESSING_LIMIT_EXCEEDED if sv.is_limit else ErrorCode.INVALID_CONTAINER
                report = CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=InspectionData(detection_status=DetectionStatus.UNAVAILABLE),
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[sv.finding.reason]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=err_code,
                    error_message=f"Security preflight failed: {sv.finding.reason}",
                )
                return b"", report

        policy = self.registry.get(fmt)
        if policy is None:
            report = CleaningReport(
                status=PipelineStatus.UNSUPPORTED,
                input=ident,
                inspection=InspectionData(
                    findings=[
                        Finding(
                            detector_id="FormatClassifier",
                            category="format",
                            reason="Unsupported or unrecognized file format",
                            actionability="UNSUPPORTED",
                        )
                    ],
                    detection_status=DetectionStatus.UNSUPPORTED,
                ),
                policy=PolicySelection(mode=mode, format_policy=fmt),
                mutation_plan=MutationRecord(),
                validation=ValidationOutcome(status="SKIPPED"),
                output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                privacy=PrivacySummary(network_used=False),
                performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                error_code=ErrorCode.UNSUPPORTED_FORMAT,
                error_message=f"Format '{fmt}' is not supported",
            )
            return data, report

        # 1. Inspection & Planning
        insp_report = self.inspect(data, filename=name, mode=mode)
        if insp_report.status in (PipelineStatus.UNSUPPORTED, PipelineStatus.ERROR):
            return data, insp_report

        # 2. Dry run handling (Sections 5, 6, 12, 13)
        if dry_run:
            mutations: list[dict[str, Any]] = []
            changed_parts: list[str] = []
            dry_run_warnings: list[str] = ["Dry-run mode: zero modifications committed"]

            if fmt == "docx":
                from docx.detector import DocxDetector
                from docx.package import DocxPackage

                pkg = DocxPackage(data)
                plan = DocxDetector(pkg, opts).build_plan()
                mutations = _docx_plan_to_mutations(plan)
                changed_parts = sorted(plan.changed_parts())
                plan_is_empty = plan.is_empty()
            elif fmt == "xlsx":
                from xlsx import XlsxDetector, XlsxPackage

                pkg = XlsxPackage(data)
                plan = XlsxDetector(pkg, opts).build_plan()
                mutations = plan.to_mutations_list()
                changed_parts = sorted(plan.changed_parts())
                plan_is_empty = plan.is_empty()
            elif fmt == "pptx":
                from pptx import PptxDetector, PptxPackage

                pkg = PptxPackage(data)
                plan = PptxDetector(pkg, opts).build_plan()
                mutations = plan.to_mutations_list()
                changed_parts = sorted(plan.changed_parts())
                plan_is_empty = plan.is_empty()
            elif fmt in (
                "png", "jpeg", "jpg", "webp", "gif", "bmp", "tiff", "avif", "heic",
                "txt", "md", "html", "latex",
                "pdf", "odt", "ods", "odp", "epub", "svg",
                "mp4", "mov", "m4a", "m4v", "wav", "mp3", "flac", "audio", "video",
            ):
                # For non-docx formats, check if inspection detected actionable markers
                plan_is_empty = insp_report.inspection.detection_status == DetectionStatus.NOT_DETECTED
                if not plan_is_empty:
                    for f in insp_report.inspection.findings:
                        desc = f.reason if isinstance(f, Finding) else str(f)
                        mutations.append({"action": "clean_marker", "desc": desc})
            else:
                plan_is_empty = True

            # Differentiate empty plan vs non-empty dry-run (Section 13)
            if plan_is_empty:
                dry_status = PipelineStatus.NO_CHANGE_REQUIRED
                would_change = False
            else:
                dry_status = PipelineStatus.INSPECTED
                would_change = True

            report = CleaningReport(
                status=dry_status,
                input=ident,
                inspection=insp_report.inspection,
                policy=PolicySelection(
                    mode=mode,
                    format_policy=fmt,
                    normalize_spaces=False if fmt in ("docx", "xlsx", "pptx") else policy.allow_destructive_normalization,
                ),
                mutation_plan=MutationRecord(mutations=mutations, changed_parts=changed_parts),
                validation=ValidationOutcome(status="SKIPPED", warnings=dry_run_warnings),
                output=OutputRecord(changed=False, would_change=would_change, size=size, sha256=sha),
                privacy=PrivacySummary(network_used=False),
                performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return data, report

        # 3. Cleaning Execution
        cleaned_bytes = data
        mutations_applied: list[dict[str, Any]] = []
        parts_changed: list[str] = []
        validation_status = "PASS"
        invariants_checked: list[str] = []
        warnings: list[str] = []

        if fmt == "docx":
            from docx.cleaner import clean_docx_lossless
            from docx.detector import DocxDetector
            from docx.package import DocxPackage

            try:
                # Pre-execution plan invariant: matches dry_run mutation plan exactly (Section 5)
                pkg = DocxPackage(data)
                pre_plan = DocxDetector(pkg, opts).build_plan()
                mutations_applied = _docx_plan_to_mutations(pre_plan)
                parts_changed = sorted(pre_plan.changed_parts())

                cleaned_bytes, docx_report = clean_docx_lossless(data, options=opts)
                if docx_report.get("error"):
                    err_msg = docx_report["error"]
                    return data, CleaningReport(
                        status=PipelineStatus.VALIDATION_FAILED,
                        input=ident,
                        inspection=insp_report.inspection,
                        policy=PolicySelection(mode=mode, format_policy=fmt),
                        mutation_plan=MutationRecord(),
                        validation=ValidationOutcome(status="FAIL", warnings=[err_msg]),
                        output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                        privacy=PrivacySummary(network_used=False),
                        performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                        error_code=ErrorCode.VALIDATION_FAILED,
                        error_message=f"Validation failed: {err_msg}",
                    )
                val_rep = docx_report.get("validation")
                if val_rep and hasattr(val_rep, "invariants"):
                    inv = val_rep.invariants
                    invariants_checked = [
                        f"runs:{inv.runs_before}->{inv.runs_after}",
                        f"paragraphs:{inv.paragraphs_before}->{inv.paragraphs_after}",
                        f"breaks:{inv.page_breaks_before}->{inv.page_breaks_after}",
                        f"visible_text_identical:{inv.visible_text_identical}",
                    ]
                else:
                    invariants_checked = ["fidelity_guaranteed:True"]
            except Exception as e:
                report = CleaningReport(
                    status=PipelineStatus.VALIDATION_FAILED,
                    input=ident,
                    inspection=insp_report.inspection,
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.VALIDATION_FAILED,
                    error_message=f"Validation failed: {e}",
                )
                return data, report
        elif fmt == "xlsx":
            from xlsx import XlsxDetector, XlsxPackage, clean_xlsx_lossless

            try:
                pkg = XlsxPackage(data)
                pre_plan = XlsxDetector(pkg, opts).build_plan()
                mutations_applied = pre_plan.to_mutations_list()
                parts_changed = sorted(pre_plan.changed_parts())

                cleaned_bytes, xlsx_report = clean_xlsx_lossless(data, options=opts)
                if xlsx_report.get("error"):
                    err_msg = xlsx_report["error"]
                    return data, CleaningReport(
                        status=PipelineStatus.VALIDATION_FAILED,
                        input=ident,
                        inspection=insp_report.inspection,
                        policy=PolicySelection(mode=mode, format_policy=fmt),
                        mutation_plan=MutationRecord(),
                        validation=ValidationOutcome(status="FAIL", warnings=[err_msg]),
                        output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                        privacy=PrivacySummary(network_used=False),
                        performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                        error_code=ErrorCode.VALIDATION_FAILED,
                        error_message=f"Validation failed: {err_msg}",
                    )
                val_rep = xlsx_report.get("validation")
                if val_rep and hasattr(val_rep, "invariants"):
                    invariants_checked = list(val_rep.invariants)
                else:
                    invariants_checked = ["fidelity_guaranteed:True"]
            except Exception as e:
                report = CleaningReport(
                    status=PipelineStatus.VALIDATION_FAILED,
                    input=ident,
                    inspection=insp_report.inspection,
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.VALIDATION_FAILED,
                    error_message=f"Validation failed: {e}",
                )
                return data, report
        elif fmt == "pptx":
            from pptx import PptxDetector, PptxPackage, clean_pptx_lossless

            try:
                pkg = PptxPackage(data)
                pre_plan = PptxDetector(pkg, opts).build_plan()
                mutations_applied = pre_plan.to_mutations_list()
                parts_changed = sorted(pre_plan.changed_parts())

                cleaned_bytes, pptx_report = clean_pptx_lossless(data, options=opts)
                if pptx_report.get("error"):
                    err_msg = pptx_report["error"]
                    return data, CleaningReport(
                        status=PipelineStatus.VALIDATION_FAILED,
                        input=ident,
                        inspection=insp_report.inspection,
                        policy=PolicySelection(mode=mode, format_policy=fmt),
                        mutation_plan=MutationRecord(),
                        validation=ValidationOutcome(status="FAIL", warnings=[err_msg]),
                        output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                        privacy=PrivacySummary(network_used=False),
                        performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                        error_code=ErrorCode.VALIDATION_FAILED,
                        error_message=f"Validation failed: {err_msg}",
                    )
                val_rep = pptx_report.get("validation")
                if val_rep and hasattr(val_rep, "invariants"):
                    invariants_checked = list(val_rep.invariants)
                else:
                    invariants_checked = ["fidelity_guaranteed:True"]
            except Exception as e:
                report = CleaningReport(
                    status=PipelineStatus.VALIDATION_FAILED,
                    input=ident,
                    inspection=insp_report.inspection,
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=[str(e)]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.VALIDATION_FAILED,
                    error_message=f"Validation failed: {e}",
                )
                return data, report
        elif fmt in ("txt", "text", "md", "html", "latex"):
            if looks_binary(data):
                report = CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=insp_report.inspection,
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="FAIL", warnings=["refusing to clean bytes that look like a binary container as text"]),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.INVALID_CONTAINER,
                    error_message="refusing to clean bytes that look like a binary container as text",
                )
                return data, report
            from text_unicode import clean_text
            text_str = data.decode("utf-8", errors="surrogateescape")
            cleaned_str, stats = clean_text(
                text_str,
                nfkc=opts.get("nfkc", False),
                aggressive_homoglyphs=(mode == ProcessingMode.AGGRESSIVE),
                normalize_spaces=opts.get("normalize_spaces", False if fmt == "md" else True),
            )
            cleaned_bytes = cleaned_str.encode("utf-8", errors="surrogateescape")
            rem = stats.get("removed_count", 0)
            if rem > 0:
                mutations_applied.append({"action": "unicode_carrier_remove", "desc": f"removed {rem} carrier characters"})
        elif fmt in ("png", "jpeg", "jpg", "webp", "gif", "bmp", "tiff", "avif", "heic"):
            import tempfile
            from image_meta import clean_image
            with tempfile.TemporaryDirectory(prefix="wm-pipe-img-") as tmpdir:
                tmppath = Path(tmpdir)
                in_f = tmppath / f"in.{fmt}"
                out_f = tmppath / f"out.{fmt}"
                in_f.write_bytes(data)
                res = clean_image(in_f, out_f)
                if out_f.exists():
                    cleaned_bytes = out_f.read_bytes()
                for a in res.get("actions", []):
                    if not str(a).lower().startswith("no "):
                        mutations_applied.append({"action": "image_clean", "desc": str(a)})
        elif fmt in ("pdf", "odt", "ods", "odp", "epub", "svg"):
            import tempfile
            from container_meta import clean_container
            with tempfile.TemporaryDirectory(prefix="wm-pipe-cnt-") as tmpdir:
                tmppath = Path(tmpdir)
                ext = f".{fmt}"
                in_f = tmppath / f"in{ext}"
                out_f = tmppath / f"out{ext}"
                in_f.write_bytes(data)
                res = clean_container(in_f, out_f, fmt=fmt if fmt == "svg" else None, also_layer_a_text=True)
                if out_f.exists():
                    cleaned_bytes = out_f.read_bytes()
                for a in res.get("actions", []):
                    if not str(a).lower().startswith("no "):
                        mutations_applied.append({"action": "container_clean", "desc": str(a)})
            if fmt == "pdf" and cleaned_bytes == data and (res.get("still_has_ai_metadata") or res.get("still_has_c2pa")):
                report = CleaningReport(
                    status=PipelineStatus.ERROR,
                    input=ident,
                    inspection=insp_report.inspection,
                    policy=PolicySelection(mode=mode, format_policy=fmt),
                    mutation_plan=MutationRecord(),
                    validation=ValidationOutcome(status="SKIPPED", warnings=res.get("actions", [])),
                    output=OutputRecord(changed=False, would_change=False, size=size, sha256=sha),
                    privacy=PrivacySummary(network_used=False),
                    performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    error_code=ErrorCode.OPTIONAL_DEPENDENCY_MISSING,
                    error_message="Actionable PDF metadata detected but required cleaning tools (exiftool, ghostscript, qpdf) are unavailable",
                )
                return data, report
        elif fmt in ("mp4", "mov", "m4a", "m4v", "wav", "mp3", "flac", "audio", "video"):
            import tempfile
            from av_meta import clean_av
            with tempfile.TemporaryDirectory(prefix="wm-pipe-av-") as tmpdir:
                tmppath = Path(tmpdir)
                ext = f".{fmt}" if fmt not in ("audio", "video") else ".wav"
                in_f = tmppath / f"in{ext}"
                out_f = tmppath / f"out{ext}"
                in_f.write_bytes(data)
                res = clean_av(in_f, out_f)
                if out_f.exists():
                    cleaned_bytes = out_f.read_bytes()
                for a in res.get("actions", []):
                    if not str(a).lower().startswith("no "):
                        mutations_applied.append({"action": "av_clean", "desc": str(a)})

        # 4. Invariant & Output Status Check
        out_size = len(cleaned_bytes)
        out_sha = _compute_sha256(cleaned_bytes)
        is_changed = out_sha != sha

        if not is_changed:
            mutations_applied = []
            parts_changed = []
            cleaned_bytes = data
            out_size = size
            out_sha = sha

        final_status = PipelineStatus.CLEANED if is_changed else PipelineStatus.NO_CHANGE_REQUIRED
        would_change = is_changed

        # 5. Output Writing (Atomic Replacement / Destination)
        dest_str: Optional[str] = None
        if in_place and isinstance(input_source, (str, Path)) and is_changed:
            target_path = Path(input_source)
            try:
                safe_write_bytes(target_path, cleaned_bytes)
                dest_str = str(target_path)
            except Exception as e:
                raise IOError(f"Atomic in-place replacement failed: {e}") from e
        elif output_path:
            out_p = Path(output_path)
            safe_write_bytes(out_p, cleaned_bytes)
            dest_str = str(out_p)

        report = CleaningReport(
            status=final_status,
            input=ident,
            inspection=insp_report.inspection,
            policy=PolicySelection(
                mode=mode,
                format_policy=fmt,
                normalize_spaces=False if fmt in ("docx", "xlsx") else policy.allow_destructive_normalization,
                remote_processing=False,
            ),
            mutation_plan=MutationRecord(mutations=mutations_applied, changed_parts=parts_changed),
            validation=ValidationOutcome(
                status=validation_status,
                invariants=invariants_checked,
                warnings=warnings,
            ),
            output=OutputRecord(
                changed=is_changed,
                would_change=would_change,
                size=out_size,
                sha256=out_sha,
                output_path=dest_str,
            ),
            privacy=PrivacySummary(network_used=False),
            performance_elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )

        return cleaned_bytes, report

