"""Detector for XLSX workbooks: identifies carriers and provenance metadata."""

from __future__ import annotations

import difflib
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Optional

from text_unicode import clean_text
from .models import (
    XlsxMediaMutation,
    XlsxMetadataMutation,
    XlsxPartDrop,
    XlsxTextMutation,
)
from .mutation_plan import XlsxMutationPlan
from .package import XlsxPackage

XLSX_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

METADATA_SCRUB_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("docProps/core.xml", "dc:creator", "dc:creator"),
    ("docProps/core.xml", "cp:lastModifiedBy", "cp:lastModifiedBy"),
    ("docProps/core.xml", "dc:description", "dc:description"),
    ("docProps/core.xml", "cp:keywords", "cp:keywords"),
    ("docProps/core.xml", "dc:subject", "dc:subject"),
    ("docProps/core.xml", "cp:category", "cp:category"),
    ("docProps/app.xml", "Application", "Application"),
    ("docProps/app.xml", "Company", "Company"),
    ("docProps/app.xml", "Manager", "Manager"),
)


def _find_removed_chars(original: str, cleaned: str) -> list[tuple[int, int, str]]:
    """Return list of (offset, codepoint, char_name) for removed characters."""
    matcher = difflib.SequenceMatcher(None, original, cleaned)
    removed: list[tuple[int, int, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            for idx in range(i1, i2):
                ch = original[idx]
                cp = ord(ch)
                name = unicodedata.name(ch, "UNKNOWN_CARRIER")
                removed.append((idx, cp, name))
    return removed


class XlsxDetector:
    """Scans an XLSX package and produces an immutable XlsxMutationPlan."""

    def __init__(self, package: XlsxPackage, options: Optional[dict[str, Any]] = None):
        self.package = package
        self.options = options or {}
        self.mode = str(self.options.get("mode", "SAFE")).upper()
        # SAFE mode must NOT normalize spaces by default
        self.normalize_spaces = bool(self.options.get("normalize_spaces", False if self.mode == "SAFE" else True))
        if self.mode == "SAFE":
            self.normalize_spaces = False

    def build_plan(self) -> XlsxMutationPlan:
        """Scan package parts and compile all targeted mutations."""
        text_muts: list[XlsxTextMutation] = []
        meta_muts: list[XlsxMetadataMutation] = []
        part_drops: list[XlsxPartDrop] = []
        media_muts: list[XlsxMediaMutation] = []

        # 1. Scan shared strings: xl/sharedStrings.xml
        text_muts.extend(self._scan_shared_strings())

        # 2. Scan worksheet inline strings: xl/worksheets/sheet*.xml
        text_muts.extend(self._scan_worksheets())

        # 3. Scan metadata parts: docProps/core.xml, docProps/app.xml, docProps/custom.xml
        meta_muts.extend(self._scan_metadata())

        # 4. Scan dropped parts: customXml/*, docProps/custom.xml
        part_drops.extend(self._scan_dropped_parts())

        # 5. Scan media parts if applicable
        media_muts.extend(self._scan_media_parts())

        return XlsxMutationPlan(
            text_mutations=text_muts,
            metadata_mutations=meta_muts,
            part_drops=part_drops,
            media_mutations=media_muts,
        )

    def _scan_shared_strings(self) -> list[XlsxTextMutation]:
        muts: list[XlsxTextMutation] = []
        raw = self.package.get_member("xl/sharedStrings.xml")
        if not raw:
            return muts

        try:
            root = ET.fromstring(raw)
        except Exception:
            return muts

        # Iterate each <si> by index
        si_elements = root.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si")
        if not si_elements:
            si_elements = root.findall(".//si") or root.findall("si")

        for si_idx, si in enumerate(si_elements):
            # An <si> can contain direct <t> or <r><t> runs
            t_elements = si.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
            if not t_elements:
                t_elements = si.findall(".//t")
            for t_idx, t_elem in enumerate(t_elements):
                orig_text = t_elem.text or ""
                if not orig_text:
                    continue

                cleaned_text, stats = clean_text(
                    orig_text,
                    normalize_spaces=self.normalize_spaces,
                )
                if stats.get("removed_count", 0) > 0 or stats.get("replaced_count", 0) > 0:
                    removed_details = _find_removed_chars(orig_text, cleaned_text)
                    for offset, cp, char_name in removed_details:
                        muts.append(
                            XlsxTextMutation(
                                part_name="xl/sharedStrings.xml",
                                location=f"si:{si_idx}:t:{t_idx}:offset:{offset}",
                                codepoint=cp,
                                char_name=char_name,
                                original_text=orig_text,
                                replacement_text=cleaned_text,
                                si_idx=si_idx,
                            )
                        )
        return muts

    def _scan_worksheets(self) -> list[XlsxTextMutation]:
        muts: list[XlsxTextMutation] = []
        sheet_members = [
            m for m in self.package.member_order
            if m.startswith("xl/worksheets/sheet") and m.endswith(".xml")
        ]

        for part_name in sheet_members:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            try:
                root = ET.fromstring(raw)
            except Exception:
                continue

            sheet_name = part_name.split("/")[-1].replace(".xml", "")

            # Look for inline string cells: <c t="inlineStr"><is><t>
            c_elements = root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c")
            if not c_elements:
                c_elements = root.findall(".//c")

            for c_elem in c_elements:
                # FORMULAS ARE SACROSANCT: Ignore formula cells (<f>) unconditionally
                if (
                    c_elem.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}f") is not None
                    or c_elem.find("f") is not None
                ):
                    continue

                cell_type = c_elem.get("t", "")
                cell_ref = c_elem.get("r", "UNKNOWN")

                if cell_type == "inlineStr":
                    is_elem = c_elem.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
                    if is_elem is None:
                        is_elem = c_elem.find("is")
                    if is_elem is not None:
                        t_elements = is_elem.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                        if not t_elements:
                            t_elements = is_elem.findall(".//t")
                        for t_idx, t_elem in enumerate(t_elements):
                            orig_text = t_elem.text or ""
                            if not orig_text:
                                continue

                            cleaned_text, stats = clean_text(
                                orig_text,
                                normalize_spaces=self.normalize_spaces,
                            )
                            if stats.get("removed_count", 0) > 0 or stats.get("replaced_count", 0) > 0:
                                removed_details = _find_removed_chars(orig_text, cleaned_text)
                                for offset, cp, char_name in removed_details:
                                    muts.append(
                                        XlsxTextMutation(
                                            part_name=part_name,
                                            location=f"{sheet_name}:{cell_ref}:inlineStr:t:{t_idx}:offset:{offset}",
                                            codepoint=cp,
                                            char_name=char_name,
                                            original_text=orig_text,
                                            replacement_text=cleaned_text,
                                            cell_ref=cell_ref,
                                            sheet_name=sheet_name,
                                        )
                                    )
        return muts

    def _scan_metadata(self) -> list[XlsxMetadataMutation]:
        muts: list[XlsxMetadataMutation] = []
        for part_name, tag, field in METADATA_SCRUB_FIELDS:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            text = raw.decode("utf-8", errors="replace")
            # Tag match pattern
            pattern = rf"<{tag}\b[^>]*>(.*?)</{tag}>"
            match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
            if match and match.group(1).strip():
                val = match.group(1)
                muts.append(
                    XlsxMetadataMutation(
                        part_name=part_name,
                        tag_name=tag,
                        field_name=field,
                        original_value=val,
                        replacement_value="",
                        label=f"scrub {part_name} field {field}",
                    )
                )
        return muts

    def _scan_dropped_parts(self) -> list[XlsxPartDrop]:
        """Scan for provenance-specific parts to drop.

        Under the Phase 7 narrow SAFE metadata policy, generic custom XML and custom document
        properties are PRESERVED_RAW by default. Parts are only dropped when a specific, tested,
        high-confidence marker is explicitly recognized. Since no such marker rules currently
        exist for XLSX customXml or custom document properties, all customXml/* and
        docProps/custom.xml parts are preserved raw in SAFE mode.
        """
        drops: list[XlsxPartDrop] = []
        if self.mode == "SAFE":
            return drops
        return drops

    def _scan_media_parts(self) -> list[XlsxMediaMutation]:
        """Scan embedded media parts.

        Under Phase 7 SAFE policy, embedded media (xl/media/*) is PRESERVE_RAW.
        Embedded image cleaning is treated as an orthogonal concern.
        """
        if self.mode == "SAFE":
            return []

        media_muts: list[XlsxMediaMutation] = []
        for name in self.package.member_order:
            if re.search(
                r"^xl/media/.+\.(png|jpe?g|webp|avif|heic|gif|bmp|tiff?|svg)$",
                name,
                re.I,
            ):
                raw = self.package.get_member(name)
                if not raw:
                    continue
                import container_meta
                from image_meta import detect_format as detect_img_fmt
                img_fmt = detect_img_fmt(raw)
                sub_actions: list[str] = []
                cleaned_bytes = raw
                try:
                    if img_fmt == "png":
                        cleaned_bytes, sub_actions = container_meta.strip_png(raw, strip_all_text=True)
                    elif img_fmt == "jpeg":
                        cleaned_bytes, sub_actions = container_meta.strip_jpeg(raw, strip_all_app=True)
                    elif img_fmt == "webp":
                        cleaned_bytes, sub_actions = container_meta.strip_webp(raw, strip_all_metadata=True)
                    elif img_fmt in ("avif", "heic"):
                        cleaned_bytes, sub_actions = container_meta.strip_isobmff(raw, img_fmt, strip_all_metadata=True)
                    elif img_fmt == "gif":
                        cleaned_bytes, sub_actions = container_meta.strip_gif(raw, strip_all_metadata=True)
                    elif img_fmt == "bmp":
                        cleaned_bytes, sub_actions = container_meta.strip_bmp(raw, strip_all_metadata=True)
                    elif img_fmt == "tiff":
                        cleaned_bytes, sub_actions = container_meta.strip_tiff(raw, strip_all_metadata=True)
                    elif name.lower().endswith(".svg") or raw.lstrip().startswith(b"<"):
                        cleaned_bytes, sub_actions = container_meta.clean_svg(raw)
                except Exception:
                    pass

                if any("drop" in a.lower() for a in sub_actions) and cleaned_bytes != raw:
                    media_muts.append(
                        XlsxMediaMutation(
                            part_name=name,
                            reason=f"clean embedded media in {name} ({', '.join(sub_actions[:2])})",
                            cleaned_bytes=cleaned_bytes,
                        )
                    )
        return media_muts
