"""ClearMark v2.1 PPTX Lossless Adapter.

Dedicated high-fidelity adapter for OpenXML Presentation (.pptx) documents.
Implements the canonical lifecycle: DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE.
"""

from .cleaner import clean_pptx_lossless
from .detector import PptxDetector
from .exceptions import (
    PptxCorruptedPackageError,
    PptxError,
    PptxSecurityLimitError,
    PptxUnsupportedFeatureError,
    PptxValidationError,
)
from .models import (
    PptxFidelityReport,
    PptxMetadataMutation,
    PptxPartDrop,
    PptxTextMutation,
    PresentationFingerprint,
    ShapeFingerprint,
    SlideFingerprint,
)
from .mutation_plan import PptxMutationPlan
from .package import PptxPackage
from .patcher import PptxPatcher
from .validator import PptxFidelityValidator

__all__ = [
    "clean_pptx_lossless",
    "PptxPackage",
    "PptxDetector",
    "PptxMutationPlan",
    "PptxPatcher",
    "PptxFidelityValidator",
    "PptxFidelityReport",
    "PptxTextMutation",
    "PptxMetadataMutation",
    "PptxPartDrop",
    "ShapeFingerprint",
    "SlideFingerprint",
    "PresentationFingerprint",
    "PptxError",
    "PptxValidationError",
    "PptxCorruptedPackageError",
    "PptxSecurityLimitError",
    "PptxUnsupportedFeatureError",
]
