"""Lossless PPTX cleaner implementing DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE."""

from __future__ import annotations

from typing import Any, Optional

from .detector import PptxDetector
from .exceptions import PptxValidationError
from .package import PptxPackage
from .patcher import PptxPatcher
from .validator import PptxFidelityValidator


def clean_pptx_lossless(
    data: bytes,
    options: Optional[dict[str, Any]] = None,
) -> tuple[bytes, dict[str, Any]]:
    """Clean watermark carriers and tracking metadata from a PPTX presentation losslessly.

    Follows the canonical lifecycle:
    1. Parse package and verify fail-closed invariants
    2. Detect carriers & provenance, constructing an immutable PptxMutationPlan
    3. Return exact original bytes if plan is empty (Rule 39)
    4. Apply minimal surgical patch to targeted parts
    5. Validate all structural, shape, geometry, and raw OPC non-target invariants
    """
    opts = options or {}

    # 1. Package parse
    pkg = PptxPackage(data)

    # 2. Plan construction
    detector = PptxDetector(pkg, opts)
    plan = detector.build_plan()

    # 3. Empty plan zero-copy invariant (Rule 39)
    if plan.is_empty():
        return data, {
            "changed": False,
            "would_change": False,
            "actions": ["no PPTX metadata parts removed"],
            "validation": None,
            "plan": plan,
        }

    # 4. Minimal surgical patch
    patcher = PptxPatcher(pkg, plan, normalize_spaces=detector.normalize_spaces)
    cleaned_bytes = patcher.apply()

    # 5. Validation gate
    after_pkg = PptxPackage(cleaned_bytes)
    validator = PptxFidelityValidator(
        pkg, after_pkg, plan.changed_parts(), plan.dropped_parts()
    )
    val_report = validator.validate()

    if not val_report.passed:
        err_msg = "; ".join(val_report.errors)
        return data, {
            "changed": False,
            "would_change": True,
            "error": f"PPTX fidelity validation failed: {err_msg}",
            "actions": [],
            "validation": val_report,
            "plan": plan,
        }

    # Format human-readable actions
    actions: list[str] = []
    for mm in plan.metadata_mutations:
        actions.append(f"scrub {mm.part_name} field {mm.field_name}")
    for pd in plan.part_drops:
        actions.append(f"drop part {pd.part_name}")
    for rels_part, count in patcher.pruned_relationships.items():
        actions.append(f"prune dangling relationships x{count} in {rels_part}")
    if plan.text_mutations:
        actions.append(f"layer A text: removed={len(plan.text_mutations)} replaced=0")

    if not actions:
        actions.append("no PPTX metadata parts removed")

    return cleaned_bytes, {
        "changed": True,
        "would_change": True,
        "actions": actions,
        "validation": val_report,
        "plan": plan,
    }
