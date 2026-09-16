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
