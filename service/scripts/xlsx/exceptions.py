"""Exceptions for the XLSX lossless adapter."""

from __future__ import annotations


class XlsxFidelityException(Exception):
    """Raised when an XLSX fidelity invariant or package safety check fails."""
    pass


class XlsxUnsupportedFeatureException(XlsxFidelityException):
    """Raised when an unsupported XLSX feature (encryption, VBA macro, digital signature) is encountered."""
    pass


class XlsxPatchError(XlsxFidelityException):
    """Raised when an XLSX mutation plan cannot be applied by exact identity."""
    pass

