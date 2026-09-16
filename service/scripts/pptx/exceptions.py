"""Domain exceptions for the lossless PPTX subsystem."""

class PptxError(Exception):
    """Base exception for all PPTX processing errors."""


class PptxCorruptedPackageError(PptxError):
    """Raised when a PPTX file is not a valid OPC package or contains invalid structures."""


class PptxSecurityLimitError(PptxError):
    """Raised when an archive exceeds decompression ratio or dimension security limits."""


class PptxValidationError(PptxError):
    """Raised when post-clean fidelity or invariant verification fails."""


class PptxUnsupportedFeatureError(PptxError):
    """Raised when an unsupported feature (e.g. digital signatures, macros) is encountered."""
