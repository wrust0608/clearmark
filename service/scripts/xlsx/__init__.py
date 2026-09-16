"""ClearMark v2.1 XLSX Lossless Adapter.

Dedicated high-fidelity adapter for OpenXML Spreadsheet (.xlsx) documents.
Implements the canonical lifecycle: DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE.
"""

from .cleaner import clean_xlsx_lossless
from .detector import XlsxDetector
from .exceptions import XlsxFidelityException, XlsxUnsupportedFeatureException
from .models import (
    FormulaFingerprint,
    SharedStringFingerprint,
    SheetStructureFingerprint,
    StyleFingerprint,
    XlsxFidelityReport,
    XlsxMediaMutation,
    XlsxMetadataMutation,
    XlsxPartDrop,
    XlsxTextMutation,
)
from .mutation_plan import XlsxMutationPlan
from .package import XlsxPackage
from .patcher import XlsxPatcher
from .validator import XlsxFidelityValidator

__all__ = [
    "clean_xlsx_lossless",
    "XlsxPackage",
    "XlsxDetector",
    "XlsxMutationPlan",
    "XlsxPatcher",
    "XlsxFidelityValidator",
    "XlsxFidelityReport",
    "XlsxTextMutation",
    "XlsxMetadataMutation",
    "XlsxPartDrop",
    "XlsxMediaMutation",
    "FormulaFingerprint",
    "StyleFingerprint",
    "SheetStructureFingerprint",
    "SharedStringFingerprint",
    "XlsxFidelityException",
    "XlsxUnsupportedFeatureException",
]
