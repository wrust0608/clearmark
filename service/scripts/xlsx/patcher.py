"""Lossless XLSX patcher that applies minimal mutations to targeted XML nodes."""

from __future__ import annotations

import posixpath
import re
from typing import Optional

from text_unicode import clean_text
from .exceptions import XlsxPatchError
from .mutation_plan import XlsxMutationPlan
from .package import XlsxPackage

_TEXT_OPEN_RE = re.compile(r"<t\b[^>]*>")
_TEXT_CLOSE_RE = re.compile(r"</t>")
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


def _reencode_xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _iter_tag_blocks(text: str, open_re: re.Pattern[str], close_re: re.Pattern[str]):
    pos = 0
    while True:
        m_open = open_re.search(text, pos)
        if not m_open:
            break
        m_close = close_re.search(text, m_open.end())
        if not m_close:
            break
        yield m_open.start(), m_open.end(), m_close.start(), m_close.end()
        pos = m_close.end()


def _prune_dangling_relationships(
    rels_name: str, raw: bytes, kept_names: set[str]
) -> tuple[bytes, int]:
    base = posixpath.dirname(posixpath.dirname(rels_name))
    text = raw.decode("utf-8", errors="replace")
    dropped = [0]

    def _target_attr(tag: str) -> str:
        m = re.search(r"\bTarget\s*=\s*([\"'])(.*?)\1", tag, re.I)
        return m.group(2) if m else ""

    def _drop(m: re.Match[str]) -> str:
        tag = m.group(0)
        if re.search(r"\bTargetMode\s*=", tag, re.I):
            return tag  # external target, never pruned
        target = _target_attr(tag)
        if target.startswith("/"):
            resolved = posixpath.normpath(target.lstrip("/"))
        else:
            resolved = posixpath.normpath(posixpath.join(base, target))
        if resolved in ("", "."):
            return tag
        if resolved in kept_names:
            return tag
        dropped[0] += 1
        return ""

    new = re.sub(r"<Relationship\b[^>]*/>", _drop, text, flags=re.I)
    return new.encode("utf-8"), dropped[0]


class XlsxPatcher:
    """Applies planned mutations losslessly to an XLSX package."""

    def __init__(self, package: XlsxPackage, plan: XlsxMutationPlan, normalize_spaces: bool = False):
        self.package = package
        self.plan = plan
        self.normalize_spaces = normalize_spaces
        self.pruned_relationships: dict[str, int] = {}

    def apply(self) -> bytes:
        """Apply all planned mutations and return the rebuilt XLSX bytes.

        If the plan is empty, returns exact original bytes without modification.
        """
        if self.plan.is_empty():
            return self.package.raw_data

        changed_parts: dict[str, bytes] = {}
        dropped_parts = self.plan.dropped_parts()

        # 1. Apply text mutations
        planned_text_parts = {tm.part_name for tm in self.plan.text_mutations}
        for part_name in planned_text_parts:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            xml_text = raw.decode("utf-8", errors="replace")
            patched_xml, changed = self._patch_text_nodes(part_name, xml_text)
            if changed:
                changed_parts[part_name] = patched_xml.encode("utf-8")

        # 2. Apply metadata mutations
        planned_meta_parts = {mm.part_name for mm in self.plan.metadata_mutations}
        for part_name in planned_meta_parts:
            raw = changed_parts.get(part_name) or self.package.get_member(part_name)
            if not raw:
                continue

            text = raw.decode("utf-8", errors="replace")
            patched_text, changed = self._patch_metadata_fields(part_name, text)
            if changed:
                changed_parts[part_name] = patched_text.encode("utf-8")

        # 3. Apply media mutations
        for med in self.plan.media_mutations:
            if med.cleaned_bytes:
                changed_parts[med.part_name] = med.cleaned_bytes

        # 4. Handle dropped parts (customXml, docProps/custom.xml)
        if dropped_parts:
            # Clean [Content_Types].xml
            ct_raw = self.package.get_member("[Content_Types].xml")
            if ct_raw:
                ct_text = ct_raw.decode("utf-8", errors="replace")
                new_ct, n1 = re.subn(
                    r'<Override\b[^>]*PartName="/customXml/[^"]*"[^>]*/>',
                    "",
                    ct_text,
                )
                new_ct, n2 = re.subn(
                    r'<Override\b[^>]*PartName="/docProps/custom\.xml"[^>]*/>',
                    "",
                    new_ct,
                )
                if n1 or n2:
                    changed_parts["[Content_Types].xml"] = new_ct.encode("utf-8")

            # Prune dangling relationships
            kept_names = set(self.package.member_order) - dropped_parts
            for name in self.package.member_order:
                if name.endswith(".rels") and name not in dropped_parts:
                    raw_rels = changed_parts.get(name) or self.package.get_member(name)
                    if raw_rels:
                        pruned_raw, n_pruned = _prune_dangling_relationships(name, raw_rels, kept_names)
                        if n_pruned:
                            changed_parts[name] = pruned_raw
                            self.pruned_relationships[name] = n_pruned

        # 4. Rebuild package with strict raw non-target pass-through
        return self.package.rebuild(changed_parts, dropped_parts)

    def _patch_text_nodes(self, part_name: str, xml_text: str) -> tuple[str, bool]:
        """Surgically patch targeted <t> text elements inside existing XML markup executing exact plan."""
        out: list[str] = []
        last = 0
        changed = False

        muts = [tm for tm in self.plan.text_mutations if tm.part_name == part_name]
        if not muts:
            return xml_text, False

        # Pre-index mutations
        si_muts: dict[int, XlsxTextMutation] = {}
        cell_muts: dict[str, XlsxTextMutation] = {}
        for tm in muts:
            if tm.si_idx is not None:
                si_muts[tm.si_idx] = tm
            if tm.cell_ref:
                cell_muts[tm.cell_ref] = tm

        resolved_mut_ids: set[int] = set()

        is_sst = part_name == "xl/sharedStrings.xml"
        is_sheet = "worksheets/" in part_name

        si_re = re.compile(r"<si\b")
        c_re = re.compile(r'<c\b[^>]*\br="([^"]+)"')

        current_si = -1
        last_search_pos = 0

        for os_, oe, cs_, ce in _iter_tag_blocks(xml_text, _TEXT_OPEN_RE, _TEXT_CLOSE_RE):
            open_tag = xml_text[os_:oe]
            inner = xml_text[oe:cs_]
            close_tag = xml_text[cs_:ce]
            decoded = _decode_xml_entities(inner)

            target_tm: Optional[XlsxTextMutation] = None
            if is_sst:
                si_matches = list(si_re.finditer(xml_text, last_search_pos, os_))
                current_si += len(si_matches)
                last_search_pos = os_
                if current_si in si_muts and si_muts[current_si].original_text == decoded:
                    target_tm = si_muts[current_si]
            elif is_sheet:
                c_matches = list(c_re.finditer(xml_text[max(0, os_ - 200):os_]))
                if c_matches:
                    cell_ref = c_matches[-1].group(1)
                    if cell_ref in cell_muts and cell_muts[cell_ref].original_text == decoded:
                        target_tm = cell_muts[cell_ref]

            if not target_tm:
                continue

            resolved_mut_ids.add(id(target_tm))
            cleaned = target_tm.replacement_text

            changed = True
            # Preserve whitespace semantics (Section 24)
            if (cleaned[:1].isspace() or cleaned[-1:].isspace()) and "xml:space" not in open_tag:
                open_tag = open_tag[:-1] + ' xml:space="preserve">'
            out.append(xml_text[last:os_])
            out.append(open_tag + _reencode_xml_text(cleaned) + close_tag)
            last = ce

        if len(resolved_mut_ids) != len(muts):
            unresolved = len(muts) - len(resolved_mut_ids)
            raise XlsxPatchError(
                f"Fail-closed: Could not resolve exact planned identity for {unresolved} mutation(s) in {part_name}"
            )

        if changed:
            out.append(xml_text[last:])
            return "".join(out), True
        return xml_text, False

    def _patch_metadata_fields(self, part_name: str, xml_text: str) -> tuple[str, bool]:
        """Scrub provenance tracking fields from docProps/core.xml and docProps/app.xml."""
        changed = False
        text = xml_text

        # Relevant mutations for this part
        tags_to_scrub = [
            mm.tag_name for mm in self.plan.metadata_mutations if mm.part_name == part_name
        ]

        for tag in tags_to_scrub:
            open_re = re.compile(rf"<{tag}\b[^>]*>", re.I)
            close_re = re.compile(rf"</{tag}>", re.I)
            out: list[str] = []
            last = 0
            n = 0
            for os_, oe, cs_, ce in _iter_tag_blocks(text, open_re, close_re):
                out.append(text[last:os_])
                # Empty element contents, preserving open and close tags
                out.append(text[os_:oe] + text[cs_:ce])
                last = ce
                if text[oe:cs_]:
                    n += 1
            if n:
                out.append(text[last:])
                text = "".join(out)
                changed = True

        return text, changed
