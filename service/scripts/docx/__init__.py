"""Lossless DOCX cleaning package."""

from __future__ import annotations

try:
    from .cleaner import clean_docx_lossless
    from .detector import DocxDetector
    from .mutation_plan import (
        DocxMutationPlan,
        MediaScrubMutation,
        MetadataFieldScrubMutation,
        PartDropMutation,
        TextCodepointMutation,
    )
    from .package import DocxPackage
    from .patcher import DocxPatcher
    from .validator import DocxFidelityException, DocxFidelityValidator
    from .visible_text import extract_canonical_visible_text, remove_planned_carriers
except (ImportError, ValueError):
    from docx.cleaner import clean_docx_lossless
    from docx.detector import DocxDetector
    from docx.mutation_plan import (
        DocxMutationPlan,
        MediaScrubMutation,
        MetadataFieldScrubMutation,
        PartDropMutation,
        TextCodepointMutation,
    )
    from docx.package import DocxPackage
    from docx.patcher import DocxPatcher
    from docx.validator import DocxFidelityException, DocxFidelityValidator
    from docx.visible_text import extract_canonical_visible_text, remove_planned_carriers

__all__ = [
    "clean_docx_lossless",
    "DocxDetector",
    "DocxFidelityException",
    "DocxFidelityValidator",
    "DocxMutationPlan",
    "DocxPackage",
    "DocxPatcher",
    "MediaScrubMutation",
    "MetadataFieldScrubMutation",
    "PartDropMutation",
    "TextCodepointMutation",
    "extract_canonical_visible_text",
    "remove_planned_carriers",
]
