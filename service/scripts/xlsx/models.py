"""Data models and mutation records for the XLSX lossless adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class XlsxTextMutation:
    """Represents a targeted surgical character removal in an XLSX text element."""

    part_name: str
    location: str
    codepoint: int
    char_name: str
    original_text: str
    replacement_text: str
    context: str = ""
    si_idx: Optional[int] = None
    cell_ref: Optional[str] = None
    sheet_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": "text",
            "part": self.part_name,
            "location": self.location,
            "codepoint": f"U+{self.codepoint:04X}",
            "desc": f"U+{self.codepoint:04X} {self.char_name}",
        }
        if self.cell_ref:
            d["cell_ref"] = self.cell_ref
        if self.sheet_name:
            d["sheet_name"] = self.sheet_name
        if self.si_idx is not None:
            d["si_idx"] = self.si_idx
        return d


@dataclass(frozen=True)
class XlsxMetadataMutation:
    """Represents a provenance or extended property scrubbing action."""

    part_name: str
    tag_name: str
    field_name: str
    original_value: str
    replacement_value: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "metadata",
            "part": self.part_name,
            "tag": self.tag_name,
            "field": self.field_name,
            "desc": self.label or f"scrub {self.part_name} field {self.field_name}",
        }


@dataclass(frozen=True)
class XlsxPartDrop:
    """Represents dropping a non-essential tracking part (e.g., customXml)."""

    part_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "part_drop",
            "part": self.part_name,
            "desc": self.reason,
        }


@dataclass(frozen=True)
class XlsxMediaMutation:
    """Represents embedded media metadata cleaning."""

    part_name: str
    reason: str
    cleaned_bytes: bytes = b""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "media",
            "part": self.part_name,
            "desc": self.reason,
        }


@dataclass(frozen=True)
class FormulaFingerprint:
    """Strict fingerprint for a worksheet formula cell."""

    sheet: str
    cell_ref: str
    formula_text: str
    formula_attrs: tuple[tuple[str, str], ...]
    cached_value: Optional[str]


@dataclass(frozen=True)
class StyleFingerprint:
    """Style identity fingerprint covering styles.xml and cell style references."""

    styles_sha256: str
    cell_styles: tuple[tuple[str, str, str], ...]  # (sheet, cell_ref, style_idx)


@dataclass(frozen=True)
class SheetStructureFingerprint:
    """Worksheet structural fingerprint."""

    sheet_name: str
    sheet_id: str
    r_id: str
    cell_count: int
    cell_addresses: tuple[str, ...]
    cell_types: tuple[tuple[str, str], ...]  # (cell_ref, type_attr)
    merged_ranges: tuple[str, ...]
    hyperlinks: tuple[str, ...]
    defined_names: tuple[str, ...]


@dataclass(frozen=True)
class SharedStringFingerprint:
    """Shared string table structural fingerprint."""

    entry_count: int
    unique_count: Optional[int]
    entry_run_counts: tuple[int, ...]
    cell_references: tuple[tuple[str, str, int], ...]  # (sheet, cell_ref, si_idx)


@dataclass
class XlsxFidelityReport:
    """Fidelity validation result report."""

    passed: bool
    invariants: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    strict_opc_passed: bool = True
