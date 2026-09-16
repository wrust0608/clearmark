"""service/scripts/pipeline_types.py

Structured data models, lifecycle states, error codes, and format policies for ClearMark v2.1.
Adheres strictly to Sections 3, 4, 5, 6, 15, 17, 24, and 26 of the master specification:
- Uniform pipeline states (INSPECTED, NO_CHANGE_REQUIRED, CLEANED, VALIDATION_FAILED, UNSUPPORTED, ERROR)
- CleaningReport schema with zero full-document text storage
- Explicit processing modes (SAFE, BALANCED, AGGRESSIVE)
- Fidelity levels (LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D)
- FormatPolicyRegistry providing central policy declaration per format
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, List, Optional, Union


class PipelineStatus(str, Enum):
    """High-level lifecycle status for all formats."""
    INSPECTED = "INSPECTED"
    NO_CHANGE_REQUIRED = "NO_CHANGE_REQUIRED"
    CLEANED = "CLEANED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


class DetectionStatus(str, Enum):
    """Specific detection status distinguishing detection, absence, unavailable tools, and unsupported formats (Section 3)."""
    DETECTED = "DETECTED"
    NOT_DETECTED = "NOT_DETECTED"
    NOT_CHECKED = "NOT_CHECKED"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"


class ErrorCode(str, Enum):
    """Standardized machine-readable error codes."""
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    INVALID_CONTAINER = "INVALID_CONTAINER"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    OPTIONAL_DEPENDENCY_MISSING = "OPTIONAL_DEPENDENCY_MISSING"
    UNSUPPORTED_ARCHIVE_FEATURE = "UNSUPPORTED_ARCHIVE_FEATURE"
    PROCESSING_LIMIT_EXCEEDED = "PROCESSING_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ProcessingMode(str, Enum):
    """User-selectable processing modes."""
    SAFE = "SAFE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"


class FidelityLevel(str, Enum):
    """Format fidelity guarantees."""
    LEVEL_A = "LEVEL_A"  # Byte-preserving non-target parts (raw OPC/ZIP stream identity)
    LEVEL_B = "LEVEL_B"  # Structural invariants (tags, runs, cells, slides, layouts)
    LEVEL_C = "LEVEL_C"  # Semantic and visible text content invariants
    LEVEL_D = "LEVEL_D"  # Visual rendering regression (pixel-identical rendering)


@dataclass
class Finding:
    """Structured inspection finding avoiding body text storage (Section 4)."""
    detector_id: str
    category: str
    actionability: str = "SAFE_TO_REMOVE"
    confidence: float = 1.0
    location: Optional[str] = None
    target_part: Optional[str] = None
    codepoint: Optional[str] = None
    metadata_key: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "detector_id": self.detector_id,
            "category": self.category,
            "actionability": self.actionability,
            "confidence": self.confidence,
        }
        if self.location is not None:
            d["location"] = self.location
        if self.target_part is not None:
            d["target_part"] = self.target_part
        if self.codepoint is not None:
            d["codepoint"] = self.codepoint
        if self.metadata_key is not None:
            d["metadata_key"] = self.metadata_key
        if self.reason is not None:
            d["reason"] = self.reason
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Finding:
        return cls(
            detector_id=d.get("detector_id", ""),
            category=d.get("category", ""),
            actionability=d.get("actionability", "SAFE_TO_REMOVE"),
            confidence=float(d.get("confidence", 1.0)),
            location=d.get("location"),
            target_part=d.get("target_part"),
            codepoint=d.get("codepoint"),
            metadata_key=d.get("metadata_key"),
            reason=d.get("reason"),
        )


@dataclass(frozen=True)
class FileIdentity:
    """Input file identity and provenance."""
    filename: str
    format: str
    size: int
    sha256: str


@dataclass
class InspectionData:
    """Non-destructive inspection findings (Sections 3, 4, 9)."""
    findings: List[Union[str, dict[str, Any], Finding]] = field(default_factory=list)
    detectors_run: List[str] = field(default_factory=list)
    detectors_unavailable: List[str] = field(default_factory=list)
    unsupported_checks: List[str] = field(default_factory=list)
    detection_status: DetectionStatus = DetectionStatus.NOT_CHECKED


@dataclass
class PolicySelection:
    """Active policy configuration used during processing."""
    mode: ProcessingMode = ProcessingMode.SAFE
    format_policy: str = ""
    normalize_spaces: bool = True
    remote_processing: bool = False


@dataclass
class MutationRecord:
    """Planned and applied mutations."""
    mutations: List[dict[str, Any]] = field(default_factory=list)
    changed_parts: List[str] = field(default_factory=list)


@dataclass
class ValidationOutcome:
    """Runtime invariant verification results."""
    status: str = "SKIPPED"  # "PASS", "FAIL", "SKIPPED"
    invariants: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class OutputRecord:
    """Output file metadata (Sections 12, 13)."""
    changed: bool = False
    would_change: bool = False
    size: int = 0
    sha256: str = ""
    output_path: Optional[str] = None


@dataclass
class PrivacySummary:
    """Privacy and network usage tracking."""
    network_used: bool = False
    external_services: List[str] = field(default_factory=list)


@dataclass
class CleaningReport:
    """Universal structured report emitted by all format pipelines."""
    status: PipelineStatus
    input: FileIdentity
    inspection: InspectionData
    policy: PolicySelection
    mutation_plan: MutationRecord
    validation: ValidationOutcome
    output: OutputRecord
    privacy: PrivacySummary
    performance_elapsed_ms: float = 0.0
    error_code: Optional[ErrorCode] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert report to clean JSON-serializable dictionary."""
        findings_serialized = []
        for f in self.inspection.findings:
            if hasattr(f, "to_dict"):
                findings_serialized.append(f.to_dict())
            elif isinstance(f, dict):
                findings_serialized.append(f)
            else:
                findings_serialized.append(str(f))

        det_status = (
            self.inspection.detection_status.value
            if isinstance(self.inspection.detection_status, DetectionStatus)
            else str(self.inspection.detection_status)
        )

        return {
            "status": self.status.value if isinstance(self.status, PipelineStatus) else str(self.status),
            "input": {
                "filename": self.input.filename,
                "format": self.input.format,
                "size": self.input.size,
                "sha256": self.input.sha256,
            },
            "inspection": {
                "findings": findings_serialized,
                "detectors_run": list(self.inspection.detectors_run),
                "detectors_unavailable": list(self.inspection.detectors_unavailable),
                "unsupported_checks": list(self.inspection.unsupported_checks),
                "detection_status": det_status,
            },
            "policy": {
                "mode": self.policy.mode.value if isinstance(self.policy.mode, ProcessingMode) else str(self.policy.mode),
                "format_policy": self.policy.format_policy,
                "normalize_spaces": self.policy.normalize_spaces,
                "remote_processing": self.policy.remote_processing,
            },
            "mutation_plan": {
                "mutations": list(self.mutation_plan.mutations),
                "changed_parts": list(self.mutation_plan.changed_parts),
            },
            "validation": {
                "status": self.validation.status,
                "invariants": list(self.validation.invariants),
                "warnings": list(self.validation.warnings),
            },
            "output": {
                "changed": self.output.changed,
                "would_change": self.output.would_change,
                "size": self.output.size,
                "sha256": self.output.sha256,
                "output_path": self.output.output_path,
            },
            "privacy": {
                "network_used": self.privacy.network_used,
                "external_services": list(self.privacy.external_services),
            },
            "performance": {
                "elapsed_ms": round(self.performance_elapsed_ms, 2),
            },
            "error_code": self.error_code.value if self.error_code else None,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CleaningReport:
        """Construct CleaningReport from serialized dictionary."""
        inp = d.get("input", {})
        insp = d.get("inspection", {})
        pol = d.get("policy", {})
        mut = d.get("mutation_plan", {})
        val = d.get("validation", {})
        out = d.get("output", {})
        priv = d.get("privacy", {})
        perf = d.get("performance", {})

        mode_val = pol.get("mode", "SAFE")
        mode = ProcessingMode(mode_val) if mode_val in ProcessingMode._value2member_map_ else ProcessingMode.SAFE

        err_val = d.get("error_code")
        err = ErrorCode(err_val) if err_val in ErrorCode._value2member_map_ else None

        raw_det_status = insp.get("detection_status", "NOT_CHECKED")
        det_status = (
            DetectionStatus(raw_det_status)
            if raw_det_status in DetectionStatus._value2member_map_
            else DetectionStatus.NOT_CHECKED
        )

        return cls(
            status=PipelineStatus(d.get("status", "ERROR")),
            input=FileIdentity(
                filename=inp.get("filename", ""),
                format=inp.get("format", ""),
                size=inp.get("size", 0),
                sha256=inp.get("sha256", ""),
            ),
            inspection=InspectionData(
                findings=inp_findings if (inp_findings := insp.get("findings")) else [],
                detectors_run=insp.get("detectors_run", []),
                detectors_unavailable=insp.get("detectors_unavailable", []),
                unsupported_checks=insp.get("unsupported_checks", []),
                detection_status=det_status,
            ),
            policy=PolicySelection(
                mode=mode,
                format_policy=pol.get("format_policy", ""),
                normalize_spaces=pol.get("normalize_spaces", True),
                remote_processing=pol.get("remote_processing", False),
            ),
            mutation_plan=MutationRecord(
                mutations=mut.get("mutations", []),
                changed_parts=mut.get("changed_parts", []),
            ),
            validation=ValidationOutcome(
                status=val.get("status", "SKIPPED"),
                invariants=val.get("invariants", []),
                warnings=val.get("warnings", []),
            ),
            output=OutputRecord(
                changed=out.get("changed", False),
                would_change=out.get("would_change", False),
                size=out.get("size", 0),
                sha256=out.get("sha256", ""),
                output_path=out.get("output_path"),
            ),
            privacy=PrivacySummary(
                network_used=priv.get("network_used", False),
                external_services=priv.get("external_services", []),
            ),
            performance_elapsed_ms=perf.get("elapsed_ms", 0.0),
            error_code=err,
            error_message=d.get("error_message"),
        )


# ---------------------------------------------------------------------------
# Aliases for specification naming alignment (Data Model per Section 5)
# ---------------------------------------------------------------------------
ProcessingStatus = PipelineStatus
InputInfo = FileIdentity
InspectionReport = InspectionData
MutationSummary = MutationRecord
ValidationReport = ValidationOutcome
OutputInfo = OutputRecord
PrivacyReport = PrivacySummary


def __getattr__(name: str) -> Any:
    """Forward policy references to format_policy.py (the single authoritative source)."""
    if name in ("FormatPolicy", "FormatPolicyRegistry", "FormatCapabilities"):
        try:
            from . import format_policy
        except (ImportError, ValueError):
            import format_policy
        return getattr(format_policy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

