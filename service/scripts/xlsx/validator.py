"""Fidelity validator for XLSX workbooks."""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
from typing import Any, Optional

from .exceptions import XlsxFidelityException
from .models import (
    FormulaFingerprint,
    SharedStringFingerprint,
    SheetStructureFingerprint,
    StyleFingerprint,
    XlsxFidelityReport,
)
from .package import XlsxPackage


class XlsxFidelityValidator:
    """Validates structural, formula, style, shared-string, and strict raw OPC invariants."""

    def __init__(
        self,
        before_pkg: XlsxPackage | bytes,
        after_pkg: XlsxPackage | bytes,
        planned_changed_parts: set[str],
        dropped_parts: set[str] | None = None,
    ):
        if isinstance(before_pkg, (bytes, bytearray)):
            before_pkg = XlsxPackage(before_pkg)
        if isinstance(after_pkg, (bytes, bytearray)):
            after_pkg = XlsxPackage(after_pkg)
        self.before_pkg = before_pkg
        self.after_pkg = after_pkg
        self.planned_changed = planned_changed_parts
        self.dropped = dropped_parts or set()

    def validate(self) -> XlsxFidelityReport:
        """Run all verification gates and return XlsxFidelityReport."""
        invariants: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []

        # Archive-level ZIP comment preservation invariant
        if self.before_pkg.get_archive_comment() != self.after_pkg.get_archive_comment():
            errors.append(
                f"archive-level ZIP comment drift: original comment {self.before_pkg.get_archive_comment()!r} "
                f"!= candidate comment {self.after_pkg.get_archive_comment()!r}"
            )
        else:
            invariants.append("archive_comment_preserved: True")


        # 1. Strict Raw OPC Preservation on Non-Target Members (Section 33)
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

        # 3. Workbook & Worksheet Structural Invariants (Sections 16, 17)
        struct_ok, struct_errors, struct_invs = self._validate_workbook_structure()
        if not struct_ok:
            errors.extend(struct_errors)
        else:
            invariants.extend(struct_invs)

        # 4. Formula Invariants (Section 13, 29)
        form_ok, form_errors, form_count = self._validate_formula_fingerprints()
        if not form_ok:
            errors.extend(form_errors)
        else:
            invariants.append(f"formulas_exact: {form_count} formulas identical")

        # 5. Style Invariants (Section 15, 30)
        style_ok, style_errors, style_count = self._validate_style_fingerprints()
        if not style_ok:
            errors.extend(style_errors)
        else:
            invariants.append(f"styles_identical: styles.xml sha256 invariant, {style_count} cell styles invariant")

        # 6. Shared String Table Invariants (Section 9, 10, 31)
        sst_ok, sst_errors, sst_invs = self._validate_shared_strings()
        if not sst_ok:
            errors.extend(sst_errors)
        else:
            invariants.extend(sst_invs)

        # 7. Media & Drawing Invariants (Section 18)
        media_ok, media_errors = self._validate_media_and_drawings()
        if not media_ok:
            errors.extend(media_errors)
        else:
            invariants.append("media_and_drawings_invariant: True")

        passed = len(errors) == 0
        return XlsxFidelityReport(
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
                errors.append(f"Non-target uncompressed SHA-256 drift in '{name}': {orig_hash} != {cand_hash}")

            # Raw compressed payload hash
            orig_comp_hash = self.before_pkg.get_compressed_hash(name)
            cand_comp_hash = self.after_pkg.get_compressed_hash(name)
            if orig_comp_hash != cand_comp_hash:
                errors.append(f"Non-target raw compressed payload drift in '{name}': {orig_comp_hash} != {cand_comp_hash}")

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
            return False, f"Member ordering drift: expected {expected_order}, got {self.after_pkg.member_order}"
        return True, ""

    def _validate_workbook_structure(self) -> tuple[bool, list[str], list[str]]:
        errors: list[str] = []
        invs: list[str] = []

        wb_before_raw = self.before_pkg.get_member("xl/workbook.xml")
        wb_after_raw = self.after_pkg.get_member("xl/workbook.xml")
        if not wb_before_raw:
            if wb_after_raw:
                return False, ["Unexpected xl/workbook.xml added to output package"], []
            return True, [], []
        if not wb_after_raw:
            return False, ["Missing xl/workbook.xml in output package"], []

        try:
            wb_b = ET.fromstring(wb_before_raw)
            wb_a = ET.fromstring(wb_after_raw)
        except Exception as e:
            return False, [f"Failed to parse xl/workbook.xml: {e}"], []

        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheets_b = wb_b.findall(".//m:sheet", ns)
        sheets_a = wb_a.findall(".//m:sheet", ns)

        if len(sheets_b) != len(sheets_a):
            errors.append(f"Sheet count drift: {len(sheets_b)} -> {len(sheets_a)}")
            return False, errors, []

        for sb, sa in zip(sheets_b, sheets_a):
            name_b, name_a = sb.get("name"), sa.get("name")
            id_b, id_a = sb.get("sheetId"), sa.get("sheetId")
            if name_b != name_a:
                errors.append(f"Sheet name drift: '{name_b}' -> '{name_a}'")
            if id_b != id_a:
                errors.append(f"Sheet ID drift: '{id_b}' -> '{id_a}'")

        invs.append(f"sheet_count_invariant: {len(sheets_b)} sheets")

        # Defined names
        dn_b = [dn.get("name") for dn in wb_b.findall(".//m:definedName", ns)]
        dn_a = [dn.get("name") for dn in wb_a.findall(".//m:definedName", ns)]
        if dn_b != dn_a:
            errors.append(f"Defined names drift: {dn_b} -> {dn_a}")
        else:
            invs.append(f"defined_names_invariant: {len(dn_b)} names")

        # Per-worksheet structure (cells, merges, dimensions)
        for part_name in self.before_pkg.member_order:
            if not (part_name.startswith("xl/worksheets/sheet") and part_name.endswith(".xml")):
                continue

            sh_b_raw = self.before_pkg.get_member(part_name)
            sh_a_raw = self.after_pkg.get_member(part_name)
            if not sh_b_raw or not sh_a_raw:
                errors.append(f"Worksheet part missing: '{part_name}'")
                continue

            sh_b = ET.fromstring(sh_b_raw)
            sh_a = ET.fromstring(sh_a_raw)

            # Cells count & addresses
            cells_b = [c.get("r") for c in sh_b.findall(".//m:c", ns)]
            cells_a = [c.get("r") for c in sh_a.findall(".//m:c", ns)]
            if cells_b != cells_a:
                errors.append(f"Cell address list drift in '{part_name}': {len(cells_b)} -> {len(cells_a)}")

            # Merged cells
            merges_b = [m.get("ref") for m in sh_b.findall(".//m:mergeCell", ns)]
            merges_a = [m.get("ref") for m in sh_a.findall(".//m:mergeCell", ns)]
            if merges_b != merges_a:
                errors.append(f"Merged ranges drift in '{part_name}': {merges_b} -> {merges_a}")

            # Hyperlinks
            hyp_b = [h.get("ref") for h in sh_b.findall(".//m:hyperlink", ns)]
            hyp_a = [h.get("ref") for h in sh_a.findall(".//m:hyperlink", ns)]
            if hyp_b != hyp_a:
                errors.append(f"Hyperlinks drift in '{part_name}': {hyp_b} -> {hyp_a}")

        return len(errors) == 0, errors, invs

    def _validate_formula_fingerprints(self) -> tuple[bool, list[str], int]:
        errors: list[str] = []
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        count = 0

        for part_name in self.before_pkg.member_order:
            if not (part_name.startswith("xl/worksheets/sheet") and part_name.endswith(".xml")):
                continue

            sh_b_raw = self.before_pkg.get_member(part_name)
            sh_a_raw = self.after_pkg.get_member(part_name)
            if not sh_b_raw or not sh_a_raw:
                continue

            sh_b = ET.fromstring(sh_b_raw)
            sh_a = ET.fromstring(sh_a_raw)

            # Build map of cell_ref -> (formula_text, formula_attrs, cached_v)
            def _extract_formulas(root: ET.Element) -> dict[str, tuple[str, tuple, Optional[str]]]:
                m_dict: dict[str, tuple[str, tuple, Optional[str]]] = {}
                for c in root.findall(".//m:c", ns):
                    f_elem = c.find("m:f", ns)
                    if f_elem is not None:
                        ref = c.get("r", "")
                        f_text = f_elem.text or ""
                        f_attrs = tuple(sorted(f_elem.attrib.items()))
                        v_elem = c.find("m:v", ns)
                        v_text = v_elem.text if v_elem is not None else None
                        m_dict[ref] = (f_text, f_attrs, v_text)
                return m_dict

            forms_b = _extract_formulas(sh_b)
            forms_a = _extract_formulas(sh_a)

            if set(forms_b.keys()) != set(forms_a.keys()):
                errors.append(f"Formula cell set drift in '{part_name}': {set(forms_b.keys())} != {set(forms_a.keys())}")
                continue

            for ref, (ft_b, fa_b, fv_b) in forms_b.items():
                count += 1
                ft_a, fa_a, fv_a = forms_a[ref]
                if ft_b != ft_a:
                    errors.append(f"Formula text modified in '{part_name}' cell {ref}: '{ft_b}' -> '{ft_a}'")
                if fa_b != fa_a:
                    errors.append(f"Formula attributes modified in '{part_name}' cell {ref}: {fa_b} -> {fa_a}")
                if fv_b != fv_a:
                    errors.append(f"Formula cached value modified in '{part_name}' cell {ref}: '{fv_b}' -> '{fv_a}'")

        return len(errors) == 0, errors, count

    def _validate_style_fingerprints(self) -> tuple[bool, list[str], int]:
        errors: list[str] = []
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

        # xl/styles.xml SHA-256 check
        if self.before_pkg.has_member("xl/styles.xml"):
            s_b = self.before_pkg.get_hash("xl/styles.xml")
            s_a = self.after_pkg.get_hash("xl/styles.xml")
            if s_b != s_a:
                errors.append(f"xl/styles.xml payload modified: {s_b} -> {s_a}")

        # Per-cell style references
        count = 0
        for part_name in self.before_pkg.member_order:
            if not (part_name.startswith("xl/worksheets/sheet") and part_name.endswith(".xml")):
                continue

            sh_b_raw = self.before_pkg.get_member(part_name)
            sh_a_raw = self.after_pkg.get_member(part_name)
            if not sh_b_raw or not sh_a_raw:
                continue

            sh_b = ET.fromstring(sh_b_raw)
            sh_a = ET.fromstring(sh_a_raw)

            styles_b = {c.get("r"): c.get("s") for c in sh_b.findall(".//m:c", ns) if c.get("s") is not None}
            styles_a = {c.get("r"): c.get("s") for c in sh_a.findall(".//m:c", ns) if c.get("s") is not None}

            if styles_b != styles_a:
                errors.append(f"Cell style references modified in '{part_name}'")
            count += len(styles_b)

        return len(errors) == 0, errors, count

    def _validate_shared_strings(self) -> tuple[bool, list[str], list[str]]:
        errors: list[str] = []
        invs: list[str] = []
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

        if not self.before_pkg.has_member("xl/sharedStrings.xml"):
            return True, [], []

        sst_b_raw = self.before_pkg.get_member("xl/sharedStrings.xml")
        sst_a_raw = self.after_pkg.get_member("xl/sharedStrings.xml")
        if not sst_b_raw or not sst_a_raw:
            return False, ["Missing xl/sharedStrings.xml"], []

        sst_b = ET.fromstring(sst_b_raw)
        sst_a = ET.fromstring(sst_a_raw)

        # Count of <si>
        si_b = sst_b.findall("m:si", ns) or sst_b.findall(".//si") or sst_b.findall("si")
        si_a = sst_a.findall("m:si", ns) or sst_a.findall(".//si") or sst_a.findall("si")

        if len(si_b) != len(si_a):
            errors.append(f"Shared string count drift: {len(si_b)} -> {len(si_a)}")
            return False, errors, []

        invs.append(f"shared_string_entry_count_invariant: {len(si_b)} entries")

        # Invariant attributes: count and uniqueCount
        if sst_b.get("count") != sst_a.get("count"):
            errors.append(f"Shared string count attribute drift: {sst_b.get('count')} -> {sst_a.get('count')}")
        if sst_b.get("uniqueCount") != sst_a.get("uniqueCount"):
            errors.append(f"Shared string uniqueCount attribute drift: {sst_b.get('uniqueCount')} -> {sst_a.get('uniqueCount')}")

        # Invariant run counts per <si>
        for idx, (b_si, a_si) in enumerate(zip(si_b, si_a)):
            runs_b = len(b_si.findall(".//m:t", ns) or b_si.findall(".//t") or b_si.findall("t"))
            runs_a = len(a_si.findall(".//m:t", ns) or a_si.findall(".//t") or a_si.findall("t"))
            if runs_b != runs_a:
                errors.append(f"Shared string <si> {idx} run count drift: {runs_b} -> {runs_a}")

        # Worksheet cell references to shared strings (t="s" cells must point to identical index)
        for part_name in self.before_pkg.member_order:
            if not (part_name.startswith("xl/worksheets/sheet") and part_name.endswith(".xml")):
                continue

            sh_b_raw = self.before_pkg.get_member(part_name)
            sh_a_raw = self.after_pkg.get_member(part_name)
            if not sh_b_raw or not sh_a_raw:
                continue

            sh_b = ET.fromstring(sh_b_raw)
            sh_a = ET.fromstring(sh_a_raw)

            def _get_sst_refs(root: ET.Element) -> dict[str, str]:
                res: dict[str, str] = {}
                for c in root.findall(".//m:c", ns):
                    if c.get("t") == "s":
                        v = c.find("m:v", ns)
                        if v is not None:
                            res[c.get("r", "")] = v.text or ""
                return res

            sst_refs_b = _get_sst_refs(sh_b)
            sst_refs_a = _get_sst_refs(sh_a)

            if sst_refs_b != sst_refs_a:
                errors.append(f"Cell shared string index references drift in '{part_name}'")

        return len(errors) == 0, errors, invs

    def _validate_media_and_drawings(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for name in self.before_pkg.member_order:
            if name.startswith("xl/drawings/") or name.startswith("xl/charts/"):
                if name not in self.planned_changed:
                    if self.before_pkg.get_hash(name) != self.after_pkg.get_hash(name):
                        errors.append(f"Drawing/chart part modified unexpectedly: '{name}'")
            elif name.startswith("xl/media/"):
                if name not in self.planned_changed:
                    if self.before_pkg.get_hash(name) != self.after_pkg.get_hash(name):
                        errors.append(f"Media part modified unexpectedly: '{name}'")
        return len(errors) == 0, errors
