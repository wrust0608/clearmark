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


@dataclass(frozen=True)
class FormatPolicy:
    """Format Policy definition adhering to Section 15 & 17."""
    format_name: str
    extensions: tuple[str, ...]
    inspect_capabilities: tuple[str, ...]
    clean_capabilities: tuple[str, ...]
    fidelity_requirements: tuple[FidelityLevel, ...]
    destructive_operations: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    network_policy: str = "LOCAL_ONLY"
    default_mode: ProcessingMode = ProcessingMode.SAFE
    allow_destructive_normalization: bool = False


class FormatPolicyRegistry:
    """Central registry of all format policies."""

    def __init__(self) -> None:
        self._policies: dict[str, FormatPolicy] = {}

    def register(self, policy: FormatPolicy) -> None:
        self._policies[policy.format_name.lower()] = policy
        for ext in policy.extensions:
            self._policies[ext.lower().lstrip(".")] = policy

    def get(self, fmt_or_ext: str) -> Optional[FormatPolicy]:
        key = fmt_or_ext.lower().lstrip(".")
        return self._policies.get(key)

    @classmethod
    def get_default(cls) -> FormatPolicyRegistry:
        reg = cls()

        # DOCX: Frozen v2.0 Subsystem (Levels A, B, C, D)
        reg.register(
            FormatPolicy(
                format_name="docx",
                extensions=(".docx",),
                inspect_capabilities=("metadata", "docProps", "customXml", "unicode_carriers", "media_c2pa"),
                clean_capabilities=("docProps_scrub", "customXml_drop", "unicode_carrier_remove", "media_meta_strip", "raw_opc_preservation"),
                fidelity_requirements=(FidelityLevel.LEVEL_A, FidelityLevel.LEVEL_B, FidelityLevel.LEVEL_C, FidelityLevel.LEVEL_D),
                destructive_operations=(),
                optional_dependencies=(),
                network_policy="LOCAL_ONLY",
                default_mode=ProcessingMode.SAFE,
                allow_destructive_normalization=False,
            )
        )

        # XLSX: Structured OOXML Spreadsheet (Levels A, B, C)
        reg.register(
            FormatPolicy(
                format_name="xlsx",
                extensions=(".xlsx",),
                inspect_capabilities=("metadata", "docProps", "customXml", "sharedStrings", "media_c2pa"),
                clean_capabilities=("docProps_scrub", "customXml_drop", "sharedStrings_carrier_remove", "media_meta_strip", "raw_opc_preservation"),
                fidelity_requirements=(FidelityLevel.LEVEL_A, FidelityLevel.LEVEL_B, FidelityLevel.LEVEL_C),
                destructive_operations=(),
                optional_dependencies=(),
                network_policy="LOCAL_ONLY",
                default_mode=ProcessingMode.SAFE,
                allow_destructive_normalization=False,
            )
        )

        # PPTX: Structured OOXML Presentation (Levels A, B, C)
        reg.register(
            FormatPolicy(
                format_name="pptx",
                extensions=(".pptx",),
                inspect_capabilities=("metadata", "docProps", "customXml", "slide_text", "media_c2pa"),
                clean_capabilities=("docProps_scrub", "customXml_drop", "slide_carrier_remove", "media_meta_strip", "raw_opc_preservation"),
                fidelity_requirements=(FidelityLevel.LEVEL_A, FidelityLevel.LEVEL_B, FidelityLevel.LEVEL_C),
                destructive_operations=(),
                optional_dependencies=(),
                network_policy="LOCAL_ONLY",
                default_mode=ProcessingMode.SAFE,
                allow_destructive_normalization=False,
            )
        )

        # PDF: Document Container (Levels B, C)
        reg.register(
            FormatPolicy(
                format_name="pdf",
                extensions=(".pdf",),
                inspect_capabilities=("info_dict", "xmp", "c2pa", "attachments", "deep_images"),
                clean_capabilities=("info_scrub", "xmp_strip", "c2pa_strip", "attachment_meta_clean", "ghostscript_re-distill"),
                fidelity_requirements=(FidelityLevel.LEVEL_B, FidelityLevel.LEVEL_C),
                destructive_operations=("ghostscript_distill",),
                optional_dependencies=("ghostscript", "qpdf", "c2patool"),
                network_policy="LOCAL_ONLY",
                default_mode=ProcessingMode.SAFE,
                allow_destructive_normalization=False,
            )
        )

        # ODF / EPUB
        for fmt, ext in [("odt", ".odt"), ("epub", ".epub"), ("ods", ".ods"), ("odp", ".odp")]:
            reg.register(
                FormatPolicy(
                    format_name=fmt,
                    extensions=(ext,),
                    inspect_capabilities=("metadata", "manifest", "text_runs"),
                    clean_capabilities=("meta_scrub", "manifest_prune", "text_carrier_remove"),
                    fidelity_requirements=(FidelityLevel.LEVEL_B, FidelityLevel.LEVEL_C),
                    destructive_operations=(),
                    optional_dependencies=(),
                    network_policy="LOCAL_ONLY",
                    default_mode=ProcessingMode.SAFE,
                    allow_destructive_normalization=False,
                )
            )

        # Raster Images
        for fmt, exts in [
            ("png", (".png",)),
            ("jpeg", (".jpg", ".jpeg")),
            ("webp", (".webp",)),
            ("avif", (".avif",)),
            ("heic", (".heic",)),
            ("gif", (".gif",)),
            ("bmp", (".bmp",)),
            ("tiff", (".tif", ".tiff")),
        ]:
            reg.register(
                FormatPolicy(
                    format_name=fmt,
                    extensions=exts,
                    inspect_capabilities=("EXIF", "XMP", "IPTC", "C2PA", "pixel_watermark"),
                    clean_capabilities=("metadata", "EXIF", "XMP", "metadata_strip", "c2pa_strip", "pixel_watermark_inpaint"),
                    fidelity_requirements=(FidelityLevel.LEVEL_C,),
                    destructive_operations=("pixel_watermark_inpaint",),
                    optional_dependencies=("c2patool", "exiftool"),
                    network_policy="LOCAL_ONLY",
                    default_mode=ProcessingMode.SAFE,
                    allow_destructive_normalization=False,
                )
            )

        # Vector Images
        reg.register(
            FormatPolicy(
                format_name="svg",
                extensions=(".svg",),
                inspect_capabilities=("metadata_tags", "xml_comments", "c2pa"),
                clean_capabilities=("meta_tags_drop", "xml_comments_strip"),
                fidelity_requirements=(FidelityLevel.LEVEL_B, FidelityLevel.LEVEL_C),
                destructive_operations=(),
                optional_dependencies=(),
                network_policy="LOCAL_ONLY",
                default_mode=ProcessingMode.SAFE,
                allow_destructive_normalization=False,
            )
        )

        # Audio / Video
        for fmt, exts in [
            ("audio", (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a")),
            ("video", (".mp4", ".mkv", ".mov", ".avi", ".webm")),
        ]:
            reg.register(
                FormatPolicy(
                    format_name=fmt,
                    extensions=exts,
                    inspect_capabilities=("tags", "id3", "xmp", "c2pa", "audio_watermark"),
                    clean_capabilities=("tag_strip", "c2pa_strip", "audio_watermark_notch"),
                    fidelity_requirements=(FidelityLevel.LEVEL_C,),
                    destructive_operations=("audio_watermark_notch",),
                    optional_dependencies=("ffmpeg",),
                    network_policy="LOCAL_ONLY",
                    default_mode=ProcessingMode.SAFE,
                    allow_destructive_normalization=False,
                )
            )

        # Plain Text & Web Text
        for fmt, exts in [
            ("txt", (".txt",)),
            ("md", (".md", ".markdown")),
            ("html", (".html", ".htm")),
            ("latex", (".tex", ".latex")),
        ]:
            allow_norm = fmt in ("txt",)
            reg.register(
                FormatPolicy(
                    format_name=fmt,
                    extensions=exts,
                    inspect_capabilities=("invisible_unicode", "homoglyphs", "stylometry", "c2pa"),
                    clean_capabilities=("invisible_unicode_remove", "homoglyph_normalize", "semantic_rewrite"),
                    fidelity_requirements=(FidelityLevel.LEVEL_C,),
                    destructive_operations=("semantic_rewrite",) if fmt in ("txt", "md") else (),
                    optional_dependencies=(),
                    network_policy="OPTIONAL_REMOTE" if fmt in ("txt", "md") else "LOCAL_ONLY",
                    default_mode=ProcessingMode.SAFE,
                    allow_destructive_normalization=allow_norm,
                )
            )

        return reg
