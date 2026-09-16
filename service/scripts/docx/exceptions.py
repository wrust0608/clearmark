"""Custom exceptions for lossless DOCX processing."""

from __future__ import annotations


class DocxFidelityException(Exception):
    """Raised when any document fidelity invariant or security boundary is violated."""
    pass
