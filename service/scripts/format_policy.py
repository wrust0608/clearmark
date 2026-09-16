"""Per-format fidelity policies and options resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class FormatCategory(str, Enum):
    PLAIN_TEXT = "plain_text"
    WORD_PROCESSING = "word_processing"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    ODF_DOCUMENT = "odf_document"
    PDF_DOCUMENT = "pdf_document"
    RASTER_IMAGE = "raster_image"
    VECTOR_IMAGE = "vector_image"
    AUDIO_VIDEO = "audio_video"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FormatFidelityPolicy:
    fmt: str
    category: FormatCategory
    default_normalize_spaces: bool
    allow_llm_rewrite: bool
    structural_invariants_required: bool
    fail_closed: bool = True
    strip_metadata_only: bool = False


# Policies registry
_POLICIES: dict[str, FormatFidelityPolicy] = {
    # Plain text
    "txt": FormatFidelityPolicy(
        fmt="txt",
        category=FormatCategory.PLAIN_TEXT,
        default_normalize_spaces=True,
        allow_llm_rewrite=True,
        structural_invariants_required=False,
    ),
    "text": FormatFidelityPolicy(
        fmt="text",
        category=FormatCategory.PLAIN_TEXT,
        default_normalize_spaces=True,
        allow_llm_rewrite=True,
        structural_invariants_required=False,
    ),
    "md": FormatFidelityPolicy(
        fmt="md",
        category=FormatCategory.PLAIN_TEXT,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=False,
    ),
    "html": FormatFidelityPolicy(
        fmt="html",
        category=FormatCategory.PLAIN_TEXT,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=False,
    ),
    # Wordprocessing (DOCX)
    "docx": FormatFidelityPolicy(
        fmt="docx",
        category=FormatCategory.WORD_PROCESSING,
        default_normalize_spaces=False,  # NBSP must be preserved
        allow_llm_rewrite=False,          # LLM rewrite banned on DOCX
        structural_invariants_required=True,
        fail_closed=True,
    ),
    # Spreadsheets (XLSX)
    "xlsx": FormatFidelityPolicy(
        fmt="xlsx",
        category=FormatCategory.SPREADSHEET,
        default_normalize_spaces=True,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
    ),
    # Presentations (PPTX)
    "pptx": FormatFidelityPolicy(
        fmt="pptx",
        category=FormatCategory.PRESENTATION,
        default_normalize_spaces=True,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
    ),
    # ODF
    "odt": FormatFidelityPolicy(
        fmt="odt",
        category=FormatCategory.ODF_DOCUMENT,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
    ),
    "ods": FormatFidelityPolicy(
        fmt="ods",
        category=FormatCategory.ODF_DOCUMENT,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
    ),
    # PDF
    "pdf": FormatFidelityPolicy(
        fmt="pdf",
        category=FormatCategory.PDF_DOCUMENT,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    # Images
    "png": FormatFidelityPolicy(
        fmt="png",
        category=FormatCategory.RASTER_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "jpeg": FormatFidelityPolicy(
        fmt="jpeg",
        category=FormatCategory.RASTER_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "jpg": FormatFidelityPolicy(
        fmt="jpg",
        category=FormatCategory.RASTER_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "webp": FormatFidelityPolicy(
        fmt="webp",
        category=FormatCategory.RASTER_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "avif": FormatFidelityPolicy(
        fmt="avif",
        category=FormatCategory.RASTER_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "heic": FormatFidelityPolicy(
        fmt="heic",
        category=FormatCategory.RASTER_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "gif": FormatFidelityPolicy(
        fmt="gif",
        category=FormatCategory.RASTER_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "svg": FormatFidelityPolicy(
        fmt="svg",
        category=FormatCategory.VECTOR_IMAGE,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    # Audio / Video
    "mp4": FormatFidelityPolicy(
        fmt="mp4",
        category=FormatCategory.AUDIO_VIDEO,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "mp3": FormatFidelityPolicy(
        fmt="mp3",
        category=FormatCategory.AUDIO_VIDEO,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "wav": FormatFidelityPolicy(
        fmt="wav",
        category=FormatCategory.AUDIO_VIDEO,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
    "mkv": FormatFidelityPolicy(
        fmt="mkv",
        category=FormatCategory.AUDIO_VIDEO,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
        strip_metadata_only=True,
    ),
}


def get_format_policy(fmt_or_ext: str) -> FormatFidelityPolicy:
    key = fmt_or_ext.lower().lstrip(".")
    if key in _POLICIES:
        return _POLICIES[key]
    # Default fallback policy
    return FormatFidelityPolicy(
        fmt=key,
        category=FormatCategory.UNKNOWN,
        default_normalize_spaces=False,
        allow_llm_rewrite=False,
        structural_invariants_required=True,
    )


def resolve_options_for_format(
    fmt_or_ext: str, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve caller options against the format fidelity policy, enforcing safety boundaries."""
    policy = get_format_policy(fmt_or_ext)
    out = dict(options or {})

    # 1. Enforce LLM rewrite restriction
    if not policy.allow_llm_rewrite:
        out.pop("statistical_rewrite", None)
        out.pop("strategy", None)

    # 2. Enforce whitespace normalization policy
    if "normalize_spaces" not in out:
        out["normalize_spaces"] = policy.default_normalize_spaces
    elif not policy.default_normalize_spaces and policy.category == FormatCategory.WORD_PROCESSING:
        # For DOCX, always enforce normalize_spaces=False unless deliberately specified with special flag
        out["normalize_spaces"] = bool(out.get("force_normalize_spaces", False))

    # 3. Layer A text scrub default
    if "also_layer_a_text" not in out:
        out["also_layer_a_text"] = True

    return out


# ---------------------------------------------------------------------------
# ClearMark v2.1 Format Policy Registry (Single Source of Truth)
# ---------------------------------------------------------------------------

try:
    from .pipeline_types import FidelityLevel, ProcessingMode
except (ImportError, ValueError):
    from pipeline_types import FidelityLevel, ProcessingMode


@dataclass(frozen=True)
class FormatCapabilities:
    """Declared capabilities for a format per Section 14."""
    format_name: str
    inspect: tuple[str, ...]
    clean: tuple[str, ...]
    fidelity_levels: tuple[FidelityLevel, ...]
    optional_dependencies: tuple[str, ...]
    verify: tuple[str, ...] = ()


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
    verify_capabilities: tuple[str, ...] = ()
    supported_modes: tuple[str, ...] = ("safe", "balanced", "aggressive")

    @property
    def capabilities(self) -> FormatCapabilities:
        return FormatCapabilities(
            format_name=self.format_name,
            inspect=self.inspect_capabilities,
            clean=self.clean_capabilities,
            fidelity_levels=self.fidelity_requirements,
            optional_dependencies=self.optional_dependencies,
            verify=self.verify_capabilities,
        )


class FormatPolicyRegistry:
    """Authoritative central registry of all format policies."""

    def __init__(self) -> None:
        self._policies: dict[str, FormatPolicy] = {}

    def register(self, policy: FormatPolicy) -> None:
        self._policies[policy.format_name.lower()] = policy
        for ext in policy.extensions:
            self._policies[ext.lower().lstrip(".")] = policy

    def get(self, fmt_or_ext: str) -> Optional[FormatPolicy]:
        key = fmt_or_ext.lower().lstrip(".")
        return self._policies.get(key)

    def all_policies(self) -> list[FormatPolicy]:
        seen = set()
        out = []
        for p in self._policies.values():
            if p.format_name not in seen:
                seen.add(p.format_name)
                out.append(p)
        return sorted(out, key=lambda p: p.format_name)

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
                verify_capabilities=("structural_invariants", "raw_opc_invariants", "visible_text_exact"),
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
                supported_modes=("safe",),
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

