"""Lossless OOXML patcher that applies minimal mutations to targeted nodes."""

from __future__ import annotations

import html
import re

try:
    from .mutation_plan import DocxMutationPlan
    from .package import DocxPackage
except (ImportError, ValueError):
    from docx.mutation_plan import DocxMutationPlan
    from docx.package import DocxPackage

_TEXT_OPEN_RE = re.compile(r"<w:t\b[^>]*>")
_TEXT_CLOSE_RE = re.compile(r"</w:t>")
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


import posixpath

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
            return tag  # external (http / mailto / ...) — never pruned
        target = _target_attr(tag)
        if target.startswith("/"):
            resolved = posixpath.normpath(target.lstrip("/"))
        else:
            resolved = posixpath.normpath(posixpath.join(base, target))
        if resolved in ("", "."):
            return tag  # points at the package root
        if resolved in kept_names:
            return tag
        dropped[0] += 1
        return ""

    new = re.sub(r"<Relationship\b[^>]*/>", _drop, text, flags=re.I)
    return new.encode("utf-8"), dropped[0]


class DocxPatcher:
    """Applies planned mutations losslessly to an OPC package."""

    def __init__(self, package: DocxPackage, plan: DocxMutationPlan):
        self.package = package
        self.plan = plan
        self.pruned_relationships: dict[str, int] = {}

    def apply(self) -> bytes:
        if self.plan.is_empty():
            return self.package.raw_data

        changed_parts: dict[str, bytes] = {}
        dropped_parts = {p.part_name for p in self.plan.part_drops}

        # 1. Patch body text parts
        text_mutated_parts = {m.part_name for m in self.plan.text_mutations}
        target_cps = self.plan.target_codepoints

        for part_name in text_mutated_parts:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            xml_text = raw.decode("utf-8", errors="strict")
            patched_xml = self._patch_text_part(xml_text, target_cps)
            if patched_xml != xml_text:
                changed_parts[part_name] = patched_xml.encode("utf-8")

        # 2. Patch metadata parts (core.xml, app.xml)
        meta_mutated_parts = {m.part_name for m in self.plan.metadata_mutations}
        for part_name in meta_mutated_parts:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            fields_to_scrub = [
                m.tag_name for m in self.plan.metadata_mutations if m.part_name == part_name
            ]
            xml_text = raw.decode("utf-8", errors="strict")
            patched_xml = self._patch_metadata_part(xml_text, fields_to_scrub)
            if patched_xml != xml_text:
                changed_parts[part_name] = patched_xml.encode("utf-8")

        # 3. Apply media mutations
        for mm in self.plan.media_mutations:
            changed_parts[mm.part_name] = mm.cleaned_bytes

        # 4. Handle dropped parts relationships and overrides
        if dropped_parts:
            # Clean [Content_Types].xml
            ct_raw = self.package.get_member("[Content_Types].xml")
            if ct_raw:
                ct_text = ct_raw.decode("utf-8", errors="strict")
                new_ct = ct_text
                for dp in dropped_parts:
                    pattern = rf'<Override\b[^>]*PartName=[\"\']/{re.escape(dp)}[\"\'][^>]*?(?:/>|></Override>)'
                    new_ct = re.sub(pattern, "", new_ct, flags=re.I)
                if new_ct != ct_text:
                    changed_parts["[Content_Types].xml"] = new_ct.encode("utf-8")

            # Clean relationship files
            kept_names = {
                name for name in self.package.member_order if name not in dropped_parts
            }
            for name in self.package.member_order:
                if name.endswith(".rels") and name not in dropped_parts:
                    rels_raw = self.package.get_member(name)
                    if not rels_raw:
                        continue
                    new_rels, count = _prune_dangling_relationships(name, rels_raw, kept_names)
                    if count > 0:
                        self.pruned_relationships[name] = count
                        changed_parts[name] = new_rels

        return self.package.rebuild(changed_parts, dropped_parts)

    def _patch_text_part(self, xml_text: str, target_cps: set[int]) -> str:
        out: list[str] = []
        last = 0

        for os_, oe, cs_, ce in _iter_tag_blocks(xml_text, _TEXT_OPEN_RE, _TEXT_CLOSE_RE):
            open_tag = xml_text[os_:oe]
            inner = xml_text[oe:cs_]
            close_tag = xml_text[cs_:ce]

            decoded = _decode_xml_entities(inner)
            out_chars = []
            for ch in decoded:
                cp = ord(ch)
                if cp in target_cps:
                    if cp in (
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
                    ):
                        out_chars.append(" ")
                    continue
                out_chars.append(ch)
            cleaned = "".join(out_chars)

            if cleaned == decoded:
                # No change in this run
                continue

            # Check whitespace preservation:
            # If cleaned starts or ends with whitespace and xml:space="preserve" is not present, add it
            has_edge_space = cleaned.startswith((" ", "\t", "\n", "\r")) or cleaned.endswith(
                (" ", "\t", "\n", "\r")
            )
            if has_edge_space and 'xml:space="preserve"' not in open_tag:
                # Insert xml:space="preserve" before the closing bracket of open_tag
                open_tag = open_tag[:-1] + ' xml:space="preserve">'

            out.append(xml_text[last:os_])
            out.append(open_tag + _reencode_xml_text(cleaned) + close_tag)
            last = ce

        out.append(xml_text[last:])
        return "".join(out)

    def _patch_metadata_part(self, xml_text: str, fields: list[str]) -> str:
        new_text = xml_text
        for field_name in fields:
            pat = rf"(?:[a-zA-Z0-9_-]+:)?{re.escape(field_name)}"
            open_re = re.compile(rf"<({pat})\b[^>]*>", re.I)
            close_re = re.compile(rf"</({pat})>", re.I)
            out = []
            last = 0
            for os_, oe, cs_, ce in _iter_tag_blocks(new_text, open_re, close_re):
                out.append(new_text[last:os_])
                full_open = new_text[os_:oe]
                m = re.match(r"<([a-zA-Z0-9_:-]+)", full_open)
                matched_tag = m.group(1) if m else field_name
                out.append(f"<{matched_tag}></{matched_tag}>")
                last = ce
            out.append(new_text[last:])
            new_text = "".join(out)
        return new_text
