"""Fidelity validator for PPTX presentations."""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
from typing import Any, Optional

from .exceptions import PptxValidationError
from .models import (
    PptxFidelityReport,
    ShapeFingerprint,
    SlideFingerprint,
)
from .package import PptxPackage

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class PptxFidelityValidator:
    """Validates structural, shape, geometry, text run, and strict raw OPC invariants."""

    def __init__(
        self,
        before_pkg: PptxPackage | bytes,
        after_pkg: PptxPackage | bytes,
        planned_changed_parts: set[str] | None = None,
        dropped_parts: set[str] | None = None,
    ):
        if isinstance(before_pkg, (bytes, bytearray)):
            before_pkg = PptxPackage(before_pkg)
        if isinstance(after_pkg, (bytes, bytearray)):
            after_pkg = PptxPackage(after_pkg)
        self.before_pkg = before_pkg
        self.after_pkg = after_pkg
        if planned_changed_parts is None:
            planned_changed = {
                m
                for m in self.before_pkg.member_order
                if self.before_pkg.get_hash(m) != self.after_pkg.get_hash(m)
            }
        else:
            planned_changed = set(planned_changed_parts)
        self.planned_changed = planned_changed
        self.dropped = dropped_parts or set()

    def validate(self) -> PptxFidelityReport:
        """Run all verification gates and return PptxFidelityReport."""
        invariants: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []

        # 1. Strict Raw OPC Preservation on Non-Target Members (Rule 55)
        opc_ok, opc_errors = self._validate_raw_opc_non_targets()
        if not opc_ok:
            errors.extend(opc_errors)
        else:
            invariants.append("strict_raw_opc_non_targets_identical: True")

        # 2. Member Ordering Preservation
        order_ok, order_msg = self._validate_member_ordering()
        if not order_ok:
            errors.append(order_msg)
        else:
            invariants.append("member_ordering_preserved: True")

        # 3. Presentation Structural Invariants (Rule 16, 48)
        pres_ok, pres_errors, pres_invs = self._validate_presentation_structure()
        if not pres_ok:
            errors.extend(pres_errors)
        else:
            invariants.extend(pres_invs)

        # 4. Slide Structural Invariants, Shape Tree, Geometry, Run Structure (Rules 10-15, 45-47)
        slide_ok, slide_errors, slide_invs = self._validate_slide_structures()
        if not slide_ok:
            errors.extend(slide_errors)
        else:
            invariants.extend(slide_invs)

        # 5. Slide Masters, Layouts, Themes Invariants (Rules 18-20, 49)
        mlt_ok, mlt_errors = self._validate_masters_layouts_themes()
        if not mlt_ok:
            errors.extend(mlt_errors)
        else:
            invariants.append("masters_layouts_themes_raw_preserved: True")

        # 6. Media, Charts, Diagrams, Embeddings Invariants (Rules 23-27, 50-51)
        media_ok, media_errors = self._validate_media_and_embedded()
        if not media_ok:
            errors.extend(media_errors)
        else:
            invariants.append("media_charts_embeddings_raw_preserved: True")

        # 7. Generic Custom Properties and Custom XML (Rule 32, 71)
        custom_ok, custom_errors = self._validate_custom_data()
        if not custom_ok:
            errors.extend(custom_errors)
        else:
            invariants.append("custom_properties_and_custom_xml_preserved: True")

        passed = len(errors) == 0
        return PptxFidelityReport(
            passed=passed,
            invariants=invariants,
            warnings=warnings,
            errors=errors,
            strict_opc_passed=opc_ok,
        )

    def _validate_raw_opc_non_targets(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for name in self.before_pkg.member_order:
            if name in self.planned_changed or name in self.dropped:
                continue

            if not self.after_pkg.has_member(name):
                errors.append(f"Non-target member missing in output: '{name}'")
                continue

            # Uncompressed hash
            orig_hash = self.before_pkg.get_hash(name)
            cand_hash = self.after_pkg.get_hash(name)
            if orig_hash != cand_hash:
                errors.append(
                    f"Non-target uncompressed SHA-256 drift in '{name}': {orig_hash} != {cand_hash}"
                )

            # Raw compressed payload hash
            orig_comp_hash = self.before_pkg.get_compressed_hash(name)
            cand_comp_hash = self.after_pkg.get_compressed_hash(name)
            if orig_comp_hash != cand_comp_hash:
                errors.append(
                    f"Non-target raw compressed payload drift in '{name}': {orig_comp_hash} != {cand_comp_hash}"
                )

            # Raw local record header bytes (first 30 bytes + filename + extra)
            orig_record = self.before_pkg.get_local_record(name)
            cand_record = self.after_pkg.get_local_record(name)
            if orig_record != cand_record:
                errors.append(f"Non-target raw local record drift in '{name}'")

            # ZipInfo metadata fields
            b_info = self.before_pkg.zip_infos[name]
            a_info = self.after_pkg.zip_infos[name]
            if b_info.CRC != a_info.CRC:
                errors.append(f"Non-target CRC drift in '{name}': {b_info.CRC} != {a_info.CRC}")
            if b_info.compress_type != a_info.compress_type:
                errors.append(f"Non-target compress_type drift in '{name}'")
            if b_info.compress_size != a_info.compress_size:
                errors.append(f"Non-target compress_size drift in '{name}'")
            if b_info.file_size != a_info.file_size:
                errors.append(f"Non-target file_size drift in '{name}'")
            if b_info.flag_bits != a_info.flag_bits:
                errors.append(f"Non-target flag_bits drift in '{name}'")
            if b_info.external_attr != a_info.external_attr:
                errors.append(f"Non-target external_attr drift in '{name}'")
            if b_info.internal_attr != a_info.internal_attr:
                errors.append(f"Non-target internal_attr drift in '{name}'")
            if b_info.date_time != a_info.date_time:
                errors.append(f"Non-target timestamp drift in '{name}'")
            if b_info.extra != a_info.extra:
                errors.append(f"Non-target extra field drift in '{name}'")
            if b_info.comment != a_info.comment:
                errors.append(f"Non-target comment drift in '{name}'")

        return len(errors) == 0, errors

    def _validate_member_ordering(self) -> tuple[bool, str]:
        expected_order = [
            m for m in self.before_pkg.member_order
            if m not in self.dropped
        ]
        if self.after_pkg.member_order != expected_order:
            return (
                False,
                f"Member ordering drift: expected {expected_order}, got {self.after_pkg.member_order}",
            )
        return True, ""

    def _validate_presentation_structure(self) -> tuple[bool, list[str], list[str]]:
        errors: list[str] = []
        invs: list[str] = []

        pres_before_raw = self.before_pkg.get_member("ppt/presentation.xml")
        pres_after_raw = self.after_pkg.get_member("ppt/presentation.xml")
        if not pres_before_raw:
            if pres_after_raw:
                return False, ["Unexpected ppt/presentation.xml added to output package"], []
            return True, [], []
        if not pres_after_raw:
            return False, ["Missing ppt/presentation.xml in output package"], []

        try:
            pres_b = ET.fromstring(pres_before_raw)
            pres_a = ET.fromstring(pres_after_raw)
        except Exception as e:
            return False, [f"Failed to parse ppt/presentation.xml: {e}"], []

        ns = {
            "p": P_NS,
            "r": R_NS,
        }

        sld_id_lst_b = pres_b.find(".//p:sldIdLst", ns)
        sld_id_lst_a = pres_a.find(".//p:sldIdLst", ns)

        slides_b = sld_id_lst_b.findall("p:sldId", ns) if sld_id_lst_b is not None else []
        slides_a = sld_id_lst_a.findall("p:sldId", ns) if sld_id_lst_a is not None else []

        if len(slides_b) != len(slides_a):
            errors.append(f"Slide count drift: {len(slides_b)} -> {len(slides_a)}")
        else:
            invs.append(f"slide_count_invariant: {len(slides_b)} slides")

        # Compare slide IDs and r:id sequence
        for idx, (sb, sa) in enumerate(zip(slides_b, slides_a)):
            id_b = sb.get("id")
            id_a = sa.get("id")
            rid_b = sb.get(f"{{{R_NS}}}id") or sb.get("r:id")
            rid_a = sa.get(f"{{{R_NS}}}id") or sa.get("r:id")
            if id_b != id_a:
                errors.append(f"Slide[{idx}] id drift: {id_b} != {id_a}")
            if rid_b != rid_a:
                errors.append(f"Slide[{idx}] r:id drift: {rid_b} != {rid_a}")

        if not errors:
            invs.append("slide_ids_and_order_invariant: True")

        # Check presentation relationships
        rels_before_raw = self.before_pkg.get_member("ppt/_rels/presentation.xml.rels")
        rels_after_raw = self.after_pkg.get_member("ppt/_rels/presentation.xml.rels")
        if rels_before_raw and rels_after_raw:
            try:
                rb = ET.fromstring(rels_before_raw)
                ra = ET.fromstring(rels_after_raw)
                rel_map_b = {
                    r.get("Id"): (r.get("Type"), r.get("Target"), r.get("TargetMode"))
                    for r in rb.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
                }
                rel_map_a = {
                    r.get("Id"): (r.get("Type"), r.get("Target"), r.get("TargetMode"))
                    for r in ra.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
                }
                if rel_map_b != rel_map_a:
                    errors.append("Presentation relationships mapping drift")
                else:
                    invs.append("presentation_relationships_invariant: True")
            except Exception as e:
                errors.append(f"Failed to parse presentation.xml.rels: {e}")

        return len(errors) == 0, errors, invs

    def _validate_slide_structures(self) -> tuple[bool, list[str], list[str]]:
        errors: list[str] = []
        invs: list[str] = []

        slide_members = [
            m for m in self.before_pkg.member_order
            if m.startswith("ppt/slides/slide") and m.endswith(".xml") and not "/" in m[16:]
        ]

        for part_name in slide_members:
            if not self.after_pkg.has_member(part_name):
                errors.append(f"Missing slide in output package: {part_name}")
                continue

            raw_b = self.before_pkg.get_member(part_name)
            raw_a = self.after_pkg.get_member(part_name)
            if not raw_b or not raw_a:
                continue

            try:
                root_b = ET.fromstring(raw_b)
                root_a = ET.fromstring(raw_a)
            except Exception as e:
                errors.append(f"XML parse error in {part_name}: {e}")
                continue

            ns = {"p": P_NS, "a": A_NS, "r": R_NS}

            # 1. Shape tree structure and shape IDs
            spTree_b = root_b.find(".//p:spTree", ns)
            spTree_a = root_a.find(".//p:spTree", ns)
            if spTree_b is None:
                if spTree_a is not None:
                    errors.append(f"Unexpected p:spTree added in {part_name}")
            elif spTree_a is None:
                errors.append(f"Missing p:spTree in {part_name}")
            else:
                children_b = list(spTree_b)
                children_a = list(spTree_a)

                if len(children_b) != len(children_a):
                    errors.append(
                        f"Shape count drift in {part_name}: {len(children_b)} -> {len(children_a)}"
                    )
                else:
                    for idx, (cb, ca) in enumerate(zip(children_b, children_a)):
                        tag_b = cb.tag.split("}")[-1]
                        tag_a = ca.tag.split("}")[-1]
                        if tag_b != tag_a:
                            errors.append(
                                f"Shape[{idx}] tag drift in {part_name}: {tag_b} != {tag_a}"
                            )

                        # Check shape ID and name from cNvPr
                        cnv_b = cb.find(".//p:cNvPr", ns)
                        cnv_a = ca.find(".//p:cNvPr", ns)
                        if cnv_b is not None and cnv_a is not None:
                            id_b = cnv_b.get("id")
                            id_a = cnv_a.get("id")
                            if id_b != id_a:
                                errors.append(
                                    f"Shape[{idx}] cNvPr id drift in {part_name}: {id_b} != {id_a}"
                                )
                            name_b = cnv_b.get("name")
                            name_a = cnv_a.get("name")
                            if name_b != name_a:
                                errors.append(
                                    f"Shape[{idx}] cNvPr name drift in {part_name}: {name_b} != {name_a}"
                                )

                        # Check geometry from a:xfrm
                        xfrm_b = cb.find(".//a:xfrm", ns)
                        xfrm_a = ca.find(".//a:xfrm", ns)
                        if xfrm_b is not None and xfrm_a is not None:
                            off_b = xfrm_b.find("a:off", ns)
                            off_a = xfrm_a.find("a:off", ns)
                            if off_b is not None and off_a is not None:
                                if (off_b.get("x"), off_b.get("y")) != (off_a.get("x"), off_a.get("y")):
                                    errors.append(f"Shape[{idx}] xfrm offset drift in {part_name}")
                            ext_b = xfrm_b.find("a:ext", ns)
                            ext_a = xfrm_a.find("a:ext", ns)
                            if ext_b is not None and ext_a is not None:
                                if (ext_b.get("cx"), ext_b.get("cy")) != (ext_a.get("cx"), ext_a.get("cy")):
                                    errors.append(f"Shape[{idx}] xfrm extents drift in {part_name}")

            # 2. Paragraph and Run structural counts
            paras_b = root_b.findall(".//a:p", ns)
            paras_a = root_a.findall(".//a:p", ns)
            if len(paras_b) != len(paras_a):
                errors.append(
                    f"Paragraph count drift in {part_name}: {len(paras_b)} -> {len(paras_a)}"
                )
            else:
                for p_idx, (pb, pa) in enumerate(zip(paras_b, paras_a)):
                    # Count runs, breaks, fields
                    runs_b = pb.findall("a:r", ns)
                    runs_a = pa.findall("a:r", ns)
                    if len(runs_b) != len(runs_a):
                        errors.append(
                            f"Run count drift in {part_name} p[{p_idx}]: {len(runs_b)} -> {len(runs_a)}"
                        )
                    else:
                        # Validate run properties invariant
                        for r_idx, (rb, ra) in enumerate(zip(runs_b, runs_a)):
                            rpr_b = rb.find("a:rPr", ns)
                            rpr_a = ra.find("a:rPr", ns)
                            if (rpr_b is None) != (rpr_a is None):
                                errors.append(
                                    f"Run properties existence drift in {part_name} p[{p_idx}] r[{r_idx}]"
                                )
                            elif rpr_b is not None and rpr_a is not None:
                                if rpr_b.attrib != rpr_a.attrib:
                                    errors.append(
                                        f"Run properties attributes drift in {part_name} p[{p_idx}] r[{r_idx}]"
                                    )

                    brs_b = pb.findall("a:br", ns)
                    brs_a = pa.findall("a:br", ns)
                    if len(brs_b) != len(brs_a):
                        errors.append(
                            f"Line break count drift in {part_name} p[{p_idx}]: {len(brs_b)} -> {len(brs_a)}"
                        )

                    flds_b = pb.findall("a:fld", ns)
                    flds_a = pa.findall("a:fld", ns)
                    if len(flds_b) != len(flds_a):
                        errors.append(
                            f"Field count drift in {part_name} p[{p_idx}]: {len(flds_b)} -> {len(flds_a)}"
                        )
                    else:
                        # Field text must be preserved
                        for f_idx, (fb, fa) in enumerate(zip(flds_b, flds_a)):
                            ft_b = fb.find("a:t", ns)
                            ft_a = fa.find("a:t", ns)
                            txt_b = ft_b.text if ft_b is not None else ""
                            txt_a = ft_a.text if ft_a is not None else ""
                            if txt_b != txt_a:
                                errors.append(
                                    f"Field text drift in {part_name} p[{p_idx}] fld[{f_idx}]: '{txt_b}' != '{txt_a}'"
                                )

            # 3. Slide relationships
            rels_part = f"ppt/slides/_rels/{posixpath.basename(part_name)}.rels"
            if self.before_pkg.has_member(rels_part) and self.after_pkg.has_member(rels_part):
                raw_rb = self.before_pkg.get_member(rels_part)
                raw_ra = self.after_pkg.get_member(rels_part)
                if raw_rb and raw_ra:
                    try:
                        rb = ET.fromstring(raw_rb)
                        ra = ET.fromstring(raw_ra)
                        rel_map_b = {
                            r.get("Id"): (r.get("Type"), r.get("Target"), r.get("TargetMode"))
                            for r in rb.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
                        }
                        rel_map_a = {
                            r.get("Id"): (r.get("Type"), r.get("Target"), r.get("TargetMode"))
                            for r in ra.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
                        }
                        if rel_map_b != rel_map_a:
                            errors.append(f"Slide relationships drift in {rels_part}")
                    except Exception as e:
                        errors.append(f"Failed to parse {rels_part}: {e}")

        if not errors:
            invs.append(f"slide_structures_and_geometry_invariant: {len(slide_members)} slides checked")

        return len(errors) == 0, errors, invs

    def _validate_masters_layouts_themes(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for name in self.before_pkg.member_order:
            if (
                name.startswith("ppt/slideMasters/")
                or name.startswith("ppt/slideLayouts/")
                or name.startswith("ppt/theme/")
            ):
                if not self.after_pkg.has_member(name):
                    errors.append(f"Master/Layout/Theme part missing in output: {name}")
                    continue

                orig_hash = self.before_pkg.get_hash(name)
                cand_hash = self.after_pkg.get_hash(name)
                if orig_hash != cand_hash:
                    errors.append(
                        f"Master/Layout/Theme uncompressed SHA-256 drift in '{name}': {orig_hash} != {cand_hash}"
                    )

                orig_comp_hash = self.before_pkg.get_compressed_hash(name)
                cand_comp_hash = self.after_pkg.get_compressed_hash(name)
                if orig_comp_hash != cand_comp_hash:
                    errors.append(
                        f"Master/Layout/Theme raw compressed payload drift in '{name}'"
                    )

        return len(errors) == 0, errors

    def _validate_media_and_embedded(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for name in self.before_pkg.member_order:
            if (
                name.startswith("ppt/media/")
                or name.startswith("ppt/charts/")
                or name.startswith("ppt/diagrams/")
                or name.startswith("ppt/embeddings/")
            ):
                if not self.after_pkg.has_member(name):
                    errors.append(f"Media/Embedded part missing in output: {name}")
                    continue

                orig_hash = self.before_pkg.get_hash(name)
                cand_hash = self.after_pkg.get_hash(name)
                if orig_hash != cand_hash:
                    errors.append(
                        f"Media/Embedded uncompressed SHA-256 drift in '{name}': {orig_hash} != {cand_hash}"
                    )

                orig_comp_hash = self.before_pkg.get_compressed_hash(name)
                cand_comp_hash = self.after_pkg.get_compressed_hash(name)
                if orig_comp_hash != cand_comp_hash:
                    errors.append(
                        f"Media/Embedded raw compressed payload drift in '{name}'"
                    )

        return len(errors) == 0, errors

    def _validate_custom_data(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for name in self.before_pkg.member_order:
            if (
                name == "docProps/custom.xml"
                or name.startswith("customXml/")
            ) and name not in self.dropped:
                if not self.after_pkg.has_member(name):
                    errors.append(f"Custom data part missing in output: {name}")
                    continue

                orig_hash = self.before_pkg.get_hash(name)
                cand_hash = self.after_pkg.get_hash(name)
                if orig_hash != cand_hash:
                    errors.append(
                        f"Custom data uncompressed SHA-256 drift in '{name}': {orig_hash} != {cand_hash}"
                    )

        return len(errors) == 0, errors
