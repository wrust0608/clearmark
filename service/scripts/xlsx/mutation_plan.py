"""Mutation plan representation for XLSX lossless adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import (
    XlsxMediaMutation,
    XlsxMetadataMutation,
    XlsxPartDrop,
    XlsxTextMutation,
)


@dataclass
class XlsxMutationPlan:
    """Immutable plan specifying all targeted mutations to execute on an XLSX package."""

    text_mutations: list[XlsxTextMutation] = field(default_factory=list)
    metadata_mutations: list[XlsxMetadataMutation] = field(default_factory=list)
    part_drops: list[XlsxPartDrop] = field(default_factory=list)
    media_mutations: list[XlsxMediaMutation] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True if zero mutations are planned."""
        return not (
            self.text_mutations
            or self.metadata_mutations
            or self.part_drops
            or self.media_mutations
        )

    def changed_parts(self) -> set[str]:
        """Compute the exact set of package parts that will be modified or dropped."""
        parts: set[str] = set()
        for tm in self.text_mutations:
            parts.add(tm.part_name)
        for mm in self.metadata_mutations:
            parts.add(mm.part_name)
        for pd in self.part_drops:
            parts.add(pd.part_name)
            # Dropping customXml or custom docProps triggers relationship & content-types updates
            parts.add("_rels/.rels")
            parts.add("[Content_Types].xml")
        for med in self.media_mutations:
            parts.add(med.part_name)
        return parts

    def dropped_parts(self) -> set[str]:
        """Return set of part names to be dropped from package."""
        return {pd.part_name for pd in self.part_drops}

    def to_mutations_list(self) -> list[dict[str, Any]]:
        """Convert planned mutations to list of dicts for CleaningReport."""
        mutations: list[dict[str, Any]] = []
        for tm in self.text_mutations:
            mutations.append(tm.to_dict())
        for mm in self.metadata_mutations:
            mutations.append(mm.to_dict())
        for pd in self.part_drops:
            mutations.append(pd.to_dict())
        for med in self.media_mutations:
            mutations.append(med.to_dict())
        return mutations
