"""Detector module to identify exact watermark carriers and provenance metadata in DOCX."""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET

try:
    from .mutation_plan import (
        DocxMutationPlan,
        MetadataFieldScrubMutation,
        PartDropMutation,
        TextCodepointMutation,
    )
    from .package import DocxPackage
except (ImportError, ValueError):
    from docx.mutation_plan import (
        DocxMutationPlan,
        MetadataFieldScrubMutation,
        PartDropMutation,
        TextCodepointMutation,
    )
    from docx.package import DocxPackage

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

# Exact invisible carriers targeted in SAFE mode
SAFE_CARRIERS: frozenset[int] = frozenset(
    {
        0x00AD,  # soft hyphen
        0x034F,  # combining grapheme joiner
        0x115F,  # Hangul choseong filler (isolated)
        0x1160,  # Hangul jungseong filler (isolated)
        0x17B4,  # Khmer vowel inherent AQ (isolated)
        0x17B5,  # Khmer vowel inherent AA (isolated)
        0x180B,  # Mongolian FVS-1 (isolated)
        0x180C,  # Mongolian FVS-2 (isolated)
        0x180D,  # Mongolian FVS-3 (isolated)
        0x180E,  # Mongolian vowel separator
        0x180F,  # Mongolian FVS-4 (isolated)
        0x200B,  # zero width space
        0x200E,  # left-to-right mark
        0x200F,  # right-to-left mark
        0x202A,  # left-to-right embedding
        0x202B,  # right-to-left embedding
        0x202C,  # pop directional formatting
        0x202D,  # left-to-right override
        0x202E,  # right-to-left override
        0x2060,  # word joiner
        0x2061,  # function application
        0x2062,  # invisible times
        0x2063,  # invisible separator
        0x2064,  # invisible plus
        0x2066,  # left-to-right isolate
        0x2067,  # right-to-left isolate
        0x2068,  # first strong isolate
        0x2069,  # pop directional isolate
        0x3164,  # Hangul filler
        0xFEFF,  # zero width no-break space / BOM
        0xFFA0,  # halfwidth Hangul filler
        0xFFF9,  # interlinear annotation anchor
        0xFFFA,  # interlinear annotation separator
        0xFFFB,  # interlinear annotation terminator
    }
)

SPACE_HOMOGLYPHS: frozenset[int] = frozenset(
    {
        0x00A0,  # no-break space
        0x1680,  # Ogham space mark
        0x2000,  # en quad
        0x2001,  # em quad
        0x2002,  # en space
        0x2003,  # em space
        0x2004,  # three-per-em space
        0x2005,  # four-per-em space
        0x2006,  # six-per-em space
        0x2007,  # figure space
        0x2008,  # punctuation space
        0x2009,  # thin space
        0x200A,  # hair space
        0x202F,  # narrow no-break space
        0x205F,  # medium mathematical space
        0x3000,  # ideographic space
    }
)

CORE_PROVENANCE_TAGS = [
    ("creator", "dc:creator"),
    ("lastModifiedBy", "cp:lastModifiedBy"),
    ("description", "dc:description"),
    ("keywords", "cp:keywords"),
    ("subject", "dc:subject"),
    ("category", "cp:category"),
]

APP_PROVENANCE_TAGS = [
    ("Application", "Application"),
    ("Company", "Company"),
    ("Manager", "Manager"),
]


def _is_emoji_base(cp: int) -> bool:
    if 0x1F000 <= cp <= 0x1FAFF:
        return True
    if 0x2190 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF:
        return True
    return cp in (0x203C, 0x2049, 0x2139, 0x00A9, 0x00AE, 0x2122, 0x0023, 0x002A) or 0x0030 <= cp <= 0x0039


def _is_safe_carrier(
    cp: int,
    prev_cp: int | None = None,
    next_cp: int | None = None,
    normalize_spaces: bool = False,
) -> bool:
    """Determine if codepoint is an ungrounded invisible watermark carrier in SAFE mode."""
    if cp in SAFE_CARRIERS:
        return True

    if normalize_spaces and cp in SPACE_HOMOGLYPHS:
        return True

    # Tag characters U+E0001..U+E007F (outside standard flag sequences)
    if 0xE0001 <= cp <= 0xE007F:
        return True

    # Noncharacters
    if 0xFDD0 <= cp <= 0xFDEF or (cp & 0xFFFE) == 0xFFFE:
        return True

    # Reserved default ignorable codepoints
    if cp in (0x2065, 0xE0000) or (0xFFF0 <= cp <= 0xFFF8):
        return True

    # ZWJ / ZWNJ outside complex scripts & emoji sequences
    if cp in (0x200C, 0x200D):
        if prev_cp is not None and next_cp is not None:
            if cp == 0x200D and _is_emoji_base(prev_cp) and _is_emoji_base(next_cp):
                return False
            prev_cat = unicodedata.category(chr(prev_cp))[0]
            next_cat = unicodedata.category(chr(next_cp))[0]
            if prev_cat in ("L", "M") and next_cat in ("L", "M"):
                for start, end in ((0x0600, 0x08FF), (0x0900, 0x0DFF), (0x1780, 0x17FF)):
                    if start <= prev_cp <= end and start <= next_cp <= end:
                        return False
        return True

    # Variation selectors outside CJK / Emoji
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
        if prev_cp is not None:
            if cp in (0xFE0E, 0xFE0F) and _is_emoji_base(prev_cp):
                return False
            if (0x4E00 <= prev_cp <= 0x9FFF) or (0x3400 <= prev_cp <= 0x4DBF):
                return False
        return True

    return False


class DocxDetector:
    """Detects targeted watermark carriers and provenance elements in a DocxPackage."""

    def __init__(self, package: DocxPackage, options: dict | None = None):
        self.package = package
        self.options = options or {}
        self.mode = self.options.get("mode", "SAFE").upper()
        self.normalize_spaces = bool(self.options.get("normalize_spaces", False))
        self.also_layer_a_text = bool(self.options.get("also_layer_a_text", True))

    def build_plan(self) -> DocxMutationPlan:
        plan = DocxMutationPlan()
        self._detect_metadata(plan)
        self._detect_media(plan)
        if self.also_layer_a_text:
            self._detect_body_text(plan)
        return plan

    def _detect_media(self, plan: DocxMutationPlan) -> None:
        media_names = [
            name
            for name in self.package.member_order
            if re.match(
                r"^word/media/.+\.(png|jpe?g|webp|avif|heic|gif|bmp|tiff?|svg)$",
                name,
                re.I,
            )
        ]
        if not media_names:
            return

        import container_meta
        try:
            from .mutation_plan import MediaScrubMutation
        except (ImportError, ValueError):
            from docx.mutation_plan import MediaScrubMutation

        for name in media_names:
            raw = self.package.get_member(name)
            if not raw:
                continue
            img_fmt = container_meta.detect_image_format(raw)
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
                    cleaned_bytes, sub_actions = container_meta.strip_isobmff(
                        raw, img_fmt, strip_all_metadata=True
                    )
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
                plan.media_mutations.append(
                    MediaScrubMutation(
                        part_name=name,
                        cleaned_bytes=cleaned_bytes,
                        actions=tuple(sub_actions),
                    )
                )

    def _detect_metadata(self, plan: DocxMutationPlan) -> None:
        core_bytes = self.package.get_member("docProps/core.xml")
        if core_bytes:
            try:
                root = ET.fromstring(core_bytes)
                for tag, label in CORE_PROVENANCE_TAGS:
                    for elem in root.iter():
                        local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if local_name == tag and elem.text and elem.text.strip():
                            plan.metadata_mutations.append(
                                MetadataFieldScrubMutation("docProps/core.xml", local_name, label)
                            )
            except ET.ParseError:
                pass

        app_bytes = self.package.get_member("docProps/app.xml")
        if app_bytes:
            try:
                root = ET.fromstring(app_bytes)
                for tag, label in APP_PROVENANCE_TAGS:
                    for elem in root.iter():
                        local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if local_name == tag and elem.text and elem.text.strip():
                            plan.metadata_mutations.append(
                                MetadataFieldScrubMutation("docProps/app.xml", local_name, label)
                            )
            except ET.ParseError:
                pass

        if self.package.has_member("docProps/custom.xml"):
            plan.part_drops.append(
                PartDropMutation("docProps/custom.xml", "custom document properties")
            )

        custom_parts = [name for name in self.package.member_order if name.startswith("customXml/")]
        for cp in custom_parts:
            plan.part_drops.append(
                PartDropMutation(cp, "provenance customXml part")
            )

    def _detect_body_text(self, plan: DocxMutationPlan) -> None:
        body_parts = [
            name
            for name in self.package.member_order
            if re.match(r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes)\.xml$", name, re.I)
        ]

        for part_name in body_parts:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                continue

            for p_idx, p in enumerate(root.iter(f"{{{W_NS}}}p")):
                for r_idx, r in enumerate(p.iter(f"{{{W_NS}}}r")):
                    for t_idx, t in enumerate(r.iter(f"{{{W_NS}}}t")):
                        text = t.text or ""
                        if not text:
                            continue

                        for offset, ch in enumerate(text):
                            cp = ord(ch)
                            prev_cp = ord(text[offset - 1]) if offset > 0 else None
                            next_cp = ord(text[offset + 1]) if offset + 1 < len(text) else None

                            if _is_safe_carrier(cp, prev_cp, next_cp, self.normalize_spaces):
                                plan.text_mutations.append(
                                    TextCodepointMutation(
                                        part_name=part_name,
                                        p_idx=p_idx,
                                        r_idx=r_idx,
                                        t_idx=t_idx,
                                        codepoint=cp,
                                        char_name=unicodedata.name(ch, f"U+{cp:04X}"),
                                        offset=offset,
                                    )
                                )
