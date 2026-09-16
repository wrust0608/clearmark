"""Canonical visible text extractor for WordprocessingML."""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
TAG_P = f"{{{W_NS}}}p"
TAG_T = f"{{{W_NS}}}t"
TAG_TAB = f"{{{W_NS}}}tab"
TAG_BR = f"{{{W_NS}}}br"
TAG_CR = f"{{{W_NS}}}cr"
TAG_HYPHEN = f"{{{W_NS}}}noBreakHyphen"


def _extract_text_from_xml(xml_content: str | bytes | ET.Element) -> str:
    """Extract canonical visible text from a WordprocessingML XML part."""
    if isinstance(xml_content, ET.Element):
        root = xml_content
    elif isinstance(xml_content, str):
        try:
            root = ET.fromstring(xml_content.encode("utf-8"))
        except ET.ParseError:
            return ""
    else:
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return ""

    chunks: list[str] = []

    for p in root.iter(TAG_P):
        p_chunks: list[str] = []
        for elem in p.iter():
            tag = elem.tag
            if tag == TAG_T:
                if elem.text:
                    p_chunks.append(elem.text)
            elif tag == TAG_TAB:
                p_chunks.append("\t")
            elif tag == TAG_BR or tag == TAG_CR:
                p_chunks.append("\n")
            elif tag == TAG_HYPHEN:
                p_chunks.append("\u2011")

        chunks.append("".join(p_chunks))

    return "\n".join(chunks)


def extract_canonical_visible_text(docx_data: bytes | Any) -> str:
    """Extract canonical visible text across all body, header, footer, and footnote parts of a DOCX."""
    parts_text: list[str] = []
    body_part_pattern = re.compile(
        r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes)\.xml$", re.I
    )

    if hasattr(docx_data, "members") and hasattr(docx_data, "member_order"):
        names = sorted(
            [n for n in docx_data.member_order if body_part_pattern.match(n)],
            key=lambda x: (0 if x == "word/document.xml" else 1, x),
        )
        for name in names:
            raw = docx_data.members.get(name)
            if raw:
                part_text = _extract_text_from_xml(raw)
                if part_text:
                    parts_text.append(part_text)
    else:
        with zipfile.ZipFile(io.BytesIO(docx_data), "r") as zf:
            # Guarantee deterministic order: document first, then headers, footers, etc.
            names = sorted(
                [n for n in zf.namelist() if body_part_pattern.match(n)],
                key=lambda x: (0 if x == "word/document.xml" else 1, x),
            )
            for name in names:
                raw = zf.read(name)
                part_text = _extract_text_from_xml(raw)
                if part_text:
                    parts_text.append(part_text)

    return "\n\n".join(parts_text)


SPACE_HOMOGLYPHS = frozenset({0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000})


def remove_planned_carriers(text: str, target_codepoints: set[int]) -> str:
    """Remove ONLY the planned target codepoints from the text string."""
    if not target_codepoints:
        return text
    out = []
    for ch in text:
        cp = ord(ch)
        if cp in target_codepoints:
            if cp in SPACE_HOMOGLYPHS:
                out.append(" ")
            continue
        out.append(ch)
    return "".join(out)
