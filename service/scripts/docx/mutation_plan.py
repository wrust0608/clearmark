"""Data classes and structures for DocxMutationPlan."""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TextCodepointMutation:
    part_name: str
    p_idx: int
    r_idx: int
    t_idx: int
    codepoint: int
    char_name: str
    offset: int
    replacement: str = ""
    logical_offset: int = 0
    context_witness: str = ""
    t_block_idx: int = 0

    @property
    def char(self) -> str:
        return chr(self.codepoint)


@dataclass(frozen=True)
class MetadataFieldScrubMutation:
    part_name: str
    tag_name: str
    label: str


@dataclass(frozen=True)
class PartDropMutation:
    part_name: str
    reason: str


@dataclass(frozen=True)
class MediaScrubMutation:
    part_name: str
    cleaned_bytes: bytes
    actions: tuple[str, ...] = ()


@dataclass
class DocxMutationPlan:
    text_mutations: Sequence[TextCodepointMutation] = field(default_factory=list)
    metadata_mutations: Sequence[MetadataFieldScrubMutation] = field(default_factory=list)
    part_drops: Sequence[PartDropMutation] = field(default_factory=list)
    media_mutations: Sequence[MediaScrubMutation] = field(default_factory=list)
    surface_coverage: Mapping[str, str] = field(default_factory=dict)
    _is_frozen: bool = False

    def freeze(self) -> DocxMutationPlan:
        """Freeze the mutation plan to make it truly immutable after detection."""
        if not self._is_frozen:
            object.__setattr__(self, "text_mutations", tuple(self.text_mutations))
            object.__setattr__(self, "metadata_mutations", tuple(self.metadata_mutations))
            object.__setattr__(self, "part_drops", tuple(self.part_drops))
            object.__setattr__(self, "media_mutations", tuple(self.media_mutations))
            object.__setattr__(
                self,
                "surface_coverage",
                types.MappingProxyType(dict(self.surface_coverage)),
            )
            object.__setattr__(self, "_is_frozen", True)
        return self

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_is_frozen", False):
            raise TypeError("Cannot modify DocxMutationPlan after freeze()")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_is_frozen", False):
            raise TypeError("Cannot delete attribute from DocxMutationPlan after freeze()")
        super().__delattr__(name)

    def is_empty(self) -> bool:
        return not (
            self.text_mutations
            or self.metadata_mutations
            or self.part_drops
            or self.media_mutations
        )

    def changed_parts(self) -> set[str]:
        parts = {m.part_name for m in self.text_mutations}
        parts.update(m.part_name for m in self.metadata_mutations)
        parts.update(m.part_name for m in self.part_drops)
        parts.update(m.part_name for m in self.media_mutations)
        # Relationship files (.rels) or [Content_Types].xml may be modified if parts are dropped
        if self.part_drops:
            parts.add("[Content_Types].xml")
            parts.add("_rels/.rels")
            parts.add("word/_rels/document.xml.rels")
        return parts

    @property
    def target_codepoints(self) -> set[int]:
        return {m.codepoint for m in self.text_mutations}

    def to_dict(self) -> dict:
        codepoint_counts: dict[str, int] = {}
        for m in self.text_mutations:
            key = f"U+{m.codepoint:04X} ({m.char_name})"
            codepoint_counts[key] = codepoint_counts.get(key, 0) + 1

        return {
            "total_text_mutations": len(self.text_mutations),
            "total_metadata_mutations": len(self.metadata_mutations),
            "total_part_drops": len(self.part_drops),
            "removed_codepoints": codepoint_counts,
            "metadata_fields_scrubbed": [m.label for m in self.metadata_mutations],
            "parts_dropped": [m.part_name for m in self.part_drops],
            "surfaces": dict(self.surface_coverage),
            "frozen": self._is_frozen,
        }
