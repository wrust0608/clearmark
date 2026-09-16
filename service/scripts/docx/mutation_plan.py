"""Data classes and structures for DocxMutationPlan."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TextCodepointMutation:
    part_name: str
    p_idx: int
    r_idx: int
    t_idx: int
    codepoint: int
    char_name: str
    offset: int


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
    text_mutations: list[TextCodepointMutation] = field(default_factory=list)
    metadata_mutations: list[MetadataFieldScrubMutation] = field(default_factory=list)
    part_drops: list[PartDropMutation] = field(default_factory=list)
    media_mutations: list[MediaScrubMutation] = field(default_factory=list)

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
        }
