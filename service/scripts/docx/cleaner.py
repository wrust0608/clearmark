"""Main lossless DOCX cleaner coordinating Inspector, Detector, Plan, Patcher, and Validator."""

from __future__ import annotations

try:
    from .detector import DocxDetector
    from .package import DocxPackage
    from .patcher import DocxPatcher
    from .validator import DocxFidelityException, DocxFidelityValidator
except (ImportError, ValueError):
    from docx.detector import DocxDetector
    from docx.package import DocxPackage
    from docx.patcher import DocxPatcher
    from docx.validator import DocxFidelityException, DocxFidelityValidator


def clean_docx_lossless(
    data: bytes,
    options: dict | None = None,
) -> tuple[bytes, dict]:
    """Clean watermark carriers and provenance metadata from a DOCX package with guaranteed fidelity.

    Follows the strict pipeline:
      INSPECT -> DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT

    If validation fails, raises DocxFidelityException (Fail-Closed).
    """
    opts = dict(options or {})
    # Default policy: SAFE mode, normalize_spaces = False
    fail_closed = bool(opts.get("fail_closed", True))
    raise_on_violation = bool(opts.get("raise_on_violation", False))

    try:
        pkg = DocxPackage(data)
        detector = DocxDetector(pkg, opts)
        plan = detector.build_plan()
    except DocxFidelityException as e:
        if raise_on_violation:
            raise
        return data, {
            "changed": False,
            "mutations_count": 0,
            "changed_parts": [],
            "actions": [f"package/detection failed ({e}): rolled back to original data"],
            "fidelity_guaranteed": False,
            "error": str(e),
        }

    # If no carriers or provenance metadata found, return original bytes directly (Zero-copy)
    if plan.is_empty():
        return data, {
            "changed": False,
            "mutations_count": 0,
            "changed_parts": [],
            "actions": ["no watermark carriers or provenance metadata detected"],
            "fidelity_guaranteed": True,
        }

    patcher = DocxPatcher(pkg, plan)
    candidate_bytes = patcher.apply()

    # Strict fail-closed fidelity validation
    fail_closed = bool(opts.get("fail_closed", True))
    raise_on_violation = bool(opts.get("raise_on_violation", False))

    validator = DocxFidelityValidator(data, candidate_bytes, plan)
    try:
        val_report = validator.validate()
    except DocxFidelityException as e:
        if raise_on_violation:
            raise
        # Fail-closed: safely rollback to original input bytes (zero corruption guarantee)
        return data, {
            "changed": False,
            "mutations_count": 0,
            "changed_parts": [],
            "actions": [f"fidelity validation failed ({e}): rolled back to original data"],
            "fidelity_guaranteed": False,
            "error": str(e),
        }

    actions: list[str] = []
    for dp in plan.part_drops:
        actions.append(f"drop part {dp.part_name}")
    for rels_name, count in patcher.pruned_relationships.items():
        actions.append(f"prune dangling relationships x{count} in {rels_name}")
    for mm in plan.metadata_mutations:
        actions.append(f"scrub {mm.part_name} field {mm.label}")
    for mm in plan.media_mutations:
        actions.append(f"clean embedded media in {mm.part_name} ({', '.join(mm.actions[:2])})")
    if plan.text_mutations:
        removed_count = sum(
            1
            for m in plan.text_mutations
            if m.codepoint
            not in (
                0x00A0,
                0x1680,
                0x2000,
                0x2001,
                0x2002,
                0x2003,
                0x2004,
                0x2005,
                0x2006,
                0x2007,
                0x2008,
                0x2009,
                0x200A,
                0x202F,
                0x205F,
                0x3000,
            )
        )
        replaced_count = len(plan.text_mutations) - removed_count
        actions.append(f"layer A text: removed={removed_count} replaced={replaced_count}")

    report = {
        "changed": True,
        "mutations_count": (
            len(plan.text_mutations) + len(plan.metadata_mutations) + len(plan.part_drops)
        ),
        "changed_parts": sorted(list(plan.changed_parts())),
        "plan": plan.to_dict(),
        "validation": val_report,
        "actions": actions,
        "fidelity_guaranteed": True,
    }

    return candidate_bytes, report
