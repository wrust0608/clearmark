"""Domain models and data structures for the lossless PPTX subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class PptxTextMutation:
    """Represents a planned surgical text mutation in an <a:t> node."""

    part_name: str
    location: str
    codepoint: int
    char_name: str
    original_text: str
    replacement_text: str
    slide_name: str = ""
    shape_id: str = ""
    p_idx: int = 0
    r_idx: int = 0
    t_idx: int = 0

    @property
    def target_codepoint(self) -> str:
        return f"U+{self.codepoint:04X}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict without leaking user presentation text."""
        d: dict[str, Any] = {
            "kind": "text",
            "part": self.part_name,
            "location": self.location,
            "codepoint": f"U+{self.codepoint:04X}",
            "desc": f"U+{self.codepoint:04X} {self.char_name}",
        }
        if self.slide_name:
            d["slide"] = self.slide_name
        if self.shape_id:
            d["shape_id"] = self.shape_id
        d["p_idx"] = self.p_idx
        d["r_idx"] = self.r_idx
        d["t_idx"] = self.t_idx
        return d


@dataclass(frozen=True)
class PptxMetadataMutation:
    """Represents a planned surgical metadata modification in docProps."""

    part_name: str
    tag_name: str
    field_name: str
    original_value: str
    replacement_value: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "metadata",
            "part": self.part_name,
            "tag": self.tag_name,
            "field": self.field_name,
            "desc": self.label or f"scrub {self.part_name} field {self.field_name}",
        }


@dataclass(frozen=True)
class PptxPartDrop:
    """Represents a planned part drop mutation."""

    part_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "drop_part",
            "part": self.part_name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ShapeFingerprint:
    """Cryptographic/structural fingerprint of a shape inside p:spTree."""

    shape_id: str
    shape_name: str
    shape_type: str
    position_idx: int
    xfrm_off_x: str = ""
    xfrm_off_y: str = ""
    xfrm_ext_cx: str = ""
    xfrm_ext_cy: str = ""
    prst_geom: str = ""


@dataclass(frozen=True)
class SlideFingerprint:
    """Structural fingerprint of a slide part."""

    slide_part: str
    shapes: tuple[ShapeFingerprint, ...]
    paragraph_count: int
    run_count: int
    table_count: int
    field_count: int
    line_break_count: int
    hyperlink_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PresentationFingerprint:
    """Global presentation structural fingerprint."""

    slide_count: int
    slide_ids: tuple[str, ...]
    slide_order: tuple[str, ...]
    slide_part_targets: tuple[str, ...]
    master_parts: tuple[str, ...] = ()
    layout_parts: tuple[str, ...] = ()
    theme_parts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PptxFidelityReport:
    """Detailed verification report comparing original and candidate PPTX packages."""

    passed: bool
    invariants: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    strict_opc_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "invariants": list(self.invariants),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "strict_opc_passed": self.strict_opc_passed,
        }

