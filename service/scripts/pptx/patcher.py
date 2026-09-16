"""Lossless PPTX patcher that applies minimal mutations to targeted XML nodes."""

from __future__ import annotations

import posixpath
import re
from typing import Optional

from text_unicode import clean_text
from .detector import _decode_xml_entities, iter_slide_text_runs
from .mutation_plan import PptxMutationPlan
from .package import PptxPackage


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


class PptxPatcher:
    """Applies planned mutations losslessly to a PPTX package."""

    def __init__(
        self,
        package: PptxPackage,
        plan: PptxMutationPlan,
        normalize_spaces: bool = False,
    ):
        self.package = package
        self.plan = plan
        self.normalize_spaces = normalize_spaces
        self.pruned_relationships: dict[str, int] = {}

    def apply(self) -> bytes:
        """Apply all planned mutations and return the rebuilt PPTX bytes.

        If the plan is empty, returns exact original bytes without modification (Rule 39).
        """
        if self.plan.is_empty():
            return self.package.raw_data

        changed_parts: dict[str, bytes] = {}
        dropped_parts = self.plan.dropped_parts()

        # 1. Apply slide text mutations
        planned_text_parts = {tm.part_name for tm in self.plan.text_mutations}
        for part_name in planned_text_parts:
            raw = self.package.get_member(part_name)
            if not raw:
                continue

            xml_text = raw.decode("utf-8", errors="replace")
            patched_xml, changed = self._patch_slide_text(xml_text)
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

        # 3. Handle dropped parts (if any)
        if dropped_parts:
            # Clean [Content_Types].xml
            ct_raw = self.package.get_member("[Content_Types].xml")
            if ct_raw:
                ct_text = ct_raw.decode("utf-8", errors="replace")
                new_ct = ct_text
                for dp in dropped_parts:
                    pattern = rf'<Override\b[^>]*PartName=[\"\']/{re.escape(dp)}[\"\'][^>]*?(?:/>|></Override>)'
                    new_ct = re.sub(pattern, "", new_ct, flags=re.I)
                if new_ct != ct_text:
                    changed_parts["[Content_Types].xml"] = new_ct.encode("utf-8")

            # Prune dangling relationships
            kept_names = set(self.package.member_order) - dropped_parts
            for name in self.package.member_order:
                if name.endswith(".rels") and name not in dropped_parts:
                    raw_rels = changed_parts.get(name) or self.package.get_member(name)
                    if raw_rels:
                        pruned_raw, n_pruned = _prune_dangling_relationships(
                            name, raw_rels, kept_names
                        )
                        if n_pruned:
                            changed_parts[name] = pruned_raw
                            self.pruned_relationships[name] = n_pruned

        # 4. Rebuild package with strict raw non-target pass-through
        return self.package.rebuild(changed_parts, dropped_parts)

    def _patch_slide_text(self, xml_text: str) -> tuple[str, bool]:
        """Surgically patch targeted <a:t> elements inside existing XML markup."""
        out: list[str] = []
        last = 0
        changed = False

        for (
            tag_start,
            tag_end,
            cs_,
            ce_,
            inner,
            shape_id,
            shape_name,
            p_idx,
            r_idx,
            t_idx,
        ) in iter_slide_text_runs(xml_text):
            open_tag = xml_text[tag_start:tag_end]
            close_tag = xml_text[cs_:ce_]

            decoded = _decode_xml_entities(inner)
            cleaned, stats = clean_text(decoded, normalize_spaces=self.normalize_spaces)

            if stats.get("removed_count", 0) > 0 or stats.get("replaced_count", 0) > 0:
                changed = True
                # Preserve whitespace semantics (Rule 44)
                if (cleaned[:1].isspace() or cleaned[-1:].isspace()) and "xml:space" not in open_tag:
                    open_tag = open_tag[:-1] + ' xml:space="preserve">'
                out.append(xml_text[last:tag_start])
                out.append(open_tag + _reencode_xml_text(cleaned) + close_tag)
                last = ce_

        if changed:
            out.append(xml_text[last:])
            return "".join(out), True
        return xml_text, False

    def _patch_metadata_fields(
        self, part_name: str, xml_text: str
    ) -> tuple[str, bool]:
        """Scrub provenance tracking fields from docProps/core.xml and docProps/app.xml."""
        changed = False
        text = xml_text

        tags_to_scrub = [
            mm.tag_name
            for mm in self.plan.metadata_mutations
            if mm.part_name == part_name
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
