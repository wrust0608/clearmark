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
from typing import Any, List, Optional


class PipelineStatus(str, Enum):
    """High-level lifecycle status for all formats."""
    INSPECTED = "INSPECTED"
    NO_CHANGE_REQUIRED = "NO_CHANGE_REQUIRED"
    CLEANED = "CLEANED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


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


@dataclass(frozen=True)
class FileIdentity:
    """Input file identity and provenance."""
    filename: str
    format: str
    size: int
    sha256: str


@dataclass
class InspectionData:
    """Non-destructive inspection findings."""
    findings: List[str] = field(default_factory=list)
    detectors_run: List[str] = field(default_factory=list)
    detectors_unavailable: List[str] = field(default_factory=list)


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
    """Output file metadata."""
    changed: bool = False
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
        return {
            "status": self.status.value if isinstance(self.status, PipelineStatus) else str(self.status),
            "input": {
                "filename": self.input.filename,
                "format": self.input.format,
                "size": self.input.size,
                "sha256": self.input.sha256,
            },
            "inspection": {
                "findings": list(self.inspection.findings),
                "detectors_run": list(self.inspection.detectors_run),
                "detectors_unavailable": list(self.inspection.detectors_unavailable),
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

