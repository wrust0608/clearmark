"""Detector for PPTX presentations: identifies carriers and provenance metadata."""

from __future__ import annotations

import difflib
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Optional

from text_unicode import clean_text
from .exceptions import PptxUnsupportedFeatureError
from .models import (
    PptxMetadataMutation,
    PptxPartDrop,
    PptxTextMutation,
)
from .mutation_plan import PptxMutationPlan
from .package import PptxPackage

_TAG_RE = re.compile(r"<\s*(/)?\s*([a-zA-Z0-9_:]+)([^>]*)>")
_ID_ATTR_RE = re.compile(r'\bid=["\']([^"\']+)["\']')
_NAME_ATTR_RE = re.compile(r'\bname=["\']([^"\']+)["\']')

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

_XML_ENTITY_RE = re.compile(r"&(?:#x([0-9a-fA-F]+)|#([0-9]+)|([a-zA-Z]+));")
_XML_NAMED_ENTITIES = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
}


def _decode_xml_entities(s: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        hex_digits, decimal, named = m.group(1), m.group(2), m.group(3)
        if named:
            return _XML_NAMED_ENTITIES.get(named, m.group(0))
        codepoint = int(hex_digits, 16) if hex_digits else int(decimal)
        if codepoint == 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return m.group(0)
        try:
            return chr(codepoint)
        except ValueError:
            return m.group(0)

    return _XML_ENTITY_RE.sub(_sub, s)


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


def iter_slide_text_runs(xml_text: str):
    """Tokenizes slide XML and yields authorized user-facing text runs.

    Yields:
        tuple of (open_start, open_end, close_start, close_end, inner_text, shape_id, shape_name, p_idx, r_idx, t_idx)

    Strict scope rules:
    - Only <a:t> inside <a:r> within <p:sp> or table <a:tc>.
    - Skip <a:fld> (field text: date, time, slide number).
    - Skip <p:grpSp> (nested group shape text classified as NOT_CHECKED).
    - Preserve line breaks <a:br/>.
    """
    pos = 0
    stack: list[str] = []
    current_shape_id = ""
    current_shape_name = ""
    p_counter = 0
    r_counter = 0
    t_counter = 0

    while True:
        m = _TAG_RE.search(xml_text, pos)
        if not m:
            break

        is_closing = bool(m.group(1))
        raw_tag = m.group(2)
        local_tag = raw_tag.split(":")[-1]
        attrs = m.group(3)
        is_self_closing = attrs.strip().endswith("/")

        tag_start = m.start()
        tag_end = m.end()

        if is_closing:
            # Pop matching from stack
            while stack:
                top = stack.pop()
                if top == local_tag:
                    break
            if local_tag in ("sp", "graphicFrame"):
                current_shape_id = ""
                current_shape_name = ""
            pos = tag_end
            continue

        # Opening tag
        if local_tag in ("cNvPr", "cNvSpPr"):
            id_m = _ID_ATTR_RE.search(attrs)
            if id_m:
                current_shape_id = id_m.group(1)
            name_m = _NAME_ATTR_RE.search(attrs)
            if name_m:
                current_shape_name = name_m.group(1)

        if local_tag == "p":
            p_counter += 1
            r_counter = 0
            t_counter = 0
        elif local_tag == "r":
            r_counter += 1
            t_counter = 0

        if local_tag == "t":
            t_counter += 1
            # Find the closing </...:t>
            close_re = re.compile(rf"</\s*(?:[a-zA-Z0-9_]+:)?t\s*>")
            m_close = close_re.search(xml_text, tag_end)
            if m_close:
                cs_ = m_close.start()
                ce_ = m_close.end()
                inner = xml_text[tag_end:cs_]

                # Verify authorized scope:
                # 1. Must NOT be inside <a:fld>
                # 2. Must NOT be inside <p:grpSp>
                # 3. Must be inside <a:r>
                is_field = "fld" in stack
                is_group = "grpSp" in stack
                is_run = "r" in stack

                if is_run and not is_field and not is_group:
                    yield (
                        tag_start,
                        tag_end,
                        cs_,
                        ce_,
                        inner,
                        current_shape_id,
                        current_shape_name,
                        p_counter,
                        r_counter,
                        t_counter,
                    )
                pos = ce_
                continue

        if not is_self_closing:
            stack.append(local_tag)

        pos = tag_end


class PptxDetector:
    """Scans a PPTX package and produces an immutable PptxMutationPlan."""

    def __init__(self, package: PptxPackage, options: Optional[dict[str, Any]] = None):
        self.package = package
        self.options = options or {}
        self.mode = str(self.options.get("mode", "SAFE")).upper()
        # SAFE mode must NOT normalize spaces by default
        self.normalize_spaces = bool(
            self.options.get("normalize_spaces", False if self.mode == "SAFE" else True)
        )
        if self.mode == "SAFE":
            self.normalize_spaces = False

    def build_plan(self) -> PptxMutationPlan:
        """Scan package parts and compile all targeted mutations."""
        self._check_unsupported_features()

        text_muts: list[PptxTextMutation] = []
        meta_muts: list[PptxMetadataMutation] = []
        part_drops: list[PptxPartDrop] = []

        # 1. Scan slides: ppt/slides/slide*.xml
        text_muts.extend(self._scan_slides())

        # 2. Scan metadata: docProps/core.xml, docProps/app.xml
        meta_muts.extend(self._scan_metadata())

        return PptxMutationPlan(
            text_mutations=text_muts,
            metadata_mutations=meta_muts,
            part_drops=part_drops,
        )

    def _check_unsupported_features(self) -> None:
        """Enforce fail-closed policy on macros, digital signatures, etc."""
        for name in self.package.member_order:
            # Check macros (.pptm / vbaProject.bin)
            if (
                name.lower().endswith("vbaproject.bin")
                or name.lower().startswith("ppt/vba")
            ):
                raise PptxUnsupportedFeatureError(
                    f"Macro-enabled presentation part '{name}' is not supported for mutation (fail-closed)"
                )

            # Check digital signatures
            if (
                name.lower().startswith("_xmlsignatures/")
                or "signature" in name.lower()
            ):
                raise PptxUnsupportedFeatureError(
                    f"Digital signature part '{name}' detected: cannot mutate signed presentation (fail-closed)"
                )

    def _scan_slides(self) -> list[PptxTextMutation]:
        muts: list[PptxTextMutation] = []
        slide_members = [
            m for m in self.package.member_order
            if m.startswith("ppt/slides/slide") and m.endswith(".xml") and not "/" in m[16:]
        ]

        for part_name in slide_members:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            xml_text = raw.decode("utf-8", errors="replace")
            slide_name = part_name.split("/")[-1].replace(".xml", "")

            for (
                os_,
                oe,
                cs_,
                ce,
                inner,
                shape_id,
                shape_name,
                p_idx,
                r_idx,
                t_idx,
            ) in iter_slide_text_runs(xml_text):
                decoded = _decode_xml_entities(inner)
                if not decoded:
                    continue

                cleaned, stats = clean_text(
                    decoded,
                    normalize_spaces=self.normalize_spaces,
                )

                if stats.get("removed_count", 0) > 0 or stats.get("replaced_count", 0) > 0:
                    removed_details = _find_removed_chars(decoded, cleaned)
                    for offset, cp, char_name in removed_details:
                        muts.append(
                            PptxTextMutation(
                                part_name=part_name,
                                location=f"{slide_name}:shape:{shape_id or 'none'}:p:{p_idx}:r:{r_idx}:t:{t_idx}:offset:{offset}",
                                codepoint=cp,
                                char_name=char_name,
                                original_text=decoded,
                                replacement_text=cleaned,
                                slide_name=slide_name,
                                shape_id=shape_id,
                                p_idx=p_idx,
                                r_idx=r_idx,
                                t_idx=t_idx,
                            )
                        )

        return muts

    def _scan_metadata(self) -> list[PptxMetadataMutation]:
        muts: list[PptxMetadataMutation] = []
        for part_name, tag, field in METADATA_SCRUB_FIELDS:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            text = raw.decode("utf-8", errors="replace")
            pattern = rf"<{tag}\b[^>]*>(.*?)</{tag}>"
            match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
            if match and match.group(1).strip():
                val = match.group(1)
                muts.append(
                    PptxMetadataMutation(
                        part_name=part_name,
                        tag_name=tag,
                        field_name=field,
                        original_value=val,
                        replacement_value="",
                        label=f"scrub {part_name} field {field}",
                    )
                )
        return muts
