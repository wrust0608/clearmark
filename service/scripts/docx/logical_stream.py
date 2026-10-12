"""Logical text stream model and mapping for WordprocessingML.

Bridges the gap between raw OOXML run/text markup (<w:r><w:t>) and the canonical
contextual Unicode decision engine. Allows multi-run contextual sequences
(such as split emoji ZWJ sequences, split Arabic/Persian words, etc.) to be
evaluated with full paragraph context, while retaining exact mappings back to
individual XML nodes and character offsets.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

try:
    from ..text_unicode import classify_stream, StreamCharClassification
    from .mutation_plan import TextCodepointMutation
except (ImportError, ValueError):
    from text_unicode import classify_stream, StreamCharClassification
    from docx.mutation_plan import TextCodepointMutation

_TAG_RE = re.compile(r"<(/)?w:(p|r|t|tab|br|cr|noBreakHyphen)\b([^>]*)>", re.I)
_CLOSE_T_RE = re.compile(r"</w:t>", re.I)
_XML_ENTITY_RE = re.compile(r"&(?:#x([0-9a-fA-F]+)|#([0-9]+)|([a-zA-Z]+));")
_XML_NAMED_ENTITIES = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
}


def decode_xml_entities(s: str) -> str:
    """Decode standard and numerical XML entities to Unicode text."""
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


@dataclass
class DocxTextBlock:
    """Represents a single <w:t> element occurrence inside a Word XML part."""
    t_block_idx: int
    p_idx: int
    r_idx: int
    t_idx: int
    text: str
    open_start: int
    open_end: int
    close_start: int
    close_end: int
    open_tag: str


@dataclass(slots=True)
class StreamCharRef:
    """Mapping from a character in a logical text stream back to its OOXML location."""
    block: DocxTextBlock
    local_offset: int


@dataclass
class ParagraphStream:
    """Continuous logical visible text stream for a single Word paragraph (<w:p>)."""
    p_idx: int
    text: str
    blocks: list[DocxTextBlock]
    _char_refs: list[StreamCharRef] | None = None

    @property
    def char_refs(self) -> list[StreamCharRef]:
        if self._char_refs is None:
            refs: list[StreamCharRef] = []
            for b in self.blocks:
                for i in range(len(b.text)):
                    refs.append(StreamCharRef(block=b, local_offset=i))
            self._char_refs = refs
        return self._char_refs

    def get_char_ref(self, logical_offset: int) -> StreamCharRef:
        rem = logical_offset
        for b in self.blocks:
            blen = len(b.text)
            if rem < blen:
                return StreamCharRef(block=b, local_offset=rem)
            rem -= blen
        if self.blocks:
            last = self.blocks[-1]
            return StreamCharRef(block=last, local_offset=len(last.text))
        raise IndexError(f"Invalid logical offset {logical_offset}")


def parse_part_text_streams(xml_text: str) -> tuple[list[ParagraphStream], list[DocxTextBlock]]:
    """Parse a Word XML part into paragraph streams and an ordered list of text blocks.

    Tracks <w:p>, <w:r>, and <w:t> hierarchy while parsing entity-decoded text.
    Handles intra-paragraph breaks and tabs as boundary separators.
    """
    p_idx = -1
    r_idx = -1
    t_idx = -1
    t_block_idx = 0

    all_blocks: list[DocxTextBlock] = []
    streams: list[ParagraphStream] = []

    curr_p_blocks: list[DocxTextBlock] = []
    curr_text_chunks: list[str] = []

    pos = 0
    n = len(xml_text)

    while pos < n:
        m = _TAG_RE.search(xml_text, pos)
        if not m:
            break

        is_close = bool(m.group(1))
        tag = m.group(2).lower()

        if tag == "p":
            if not is_close:
                # New paragraph opened
                p_idx += 1
                r_idx = -1
                t_idx = -1
                curr_p_blocks = []
                curr_text_chunks = []
                pos = m.end()
            else:
                # Paragraph closed
                if curr_text_chunks or curr_p_blocks:
                    streams.append(
                        ParagraphStream(
                            p_idx=p_idx,
                            text="".join(curr_text_chunks),
                            blocks=list(curr_p_blocks),
                        )
                    )
                curr_p_blocks = []
                curr_text_chunks = []
                pos = m.end()

        elif tag == "r":
            if not is_close:
                r_idx += 1
                t_idx = -1
            pos = m.end()

        elif tag == "t" and not is_close:
            t_idx += 1
            open_start = m.start()
            open_end = m.end()
            open_tag = xml_text[open_start:open_end]

            # Find matching </w:t> using compiled regex on position
            close_m = _CLOSE_T_RE.search(xml_text, open_end)
            if close_m:
                close_start = close_m.start()
                close_end = close_m.end()
                raw_inner = xml_text[open_end:close_start]
                decoded = decode_xml_entities(raw_inner)

                block = DocxTextBlock(
                    t_block_idx=t_block_idx,
                    p_idx=p_idx,
                    r_idx=r_idx,
                    t_idx=t_idx,
                    text=decoded,
                    open_start=open_start,
                    open_end=open_end,
                    close_start=close_start,
                    close_end=close_end,
                    open_tag=open_tag,
                )
                all_blocks.append(block)
                curr_p_blocks.append(block)
                t_block_idx += 1

                curr_text_chunks.append(decoded)
                pos = close_end
            else:
                pos = open_end

        else:
            pos = m.end()

    # Flush dangling unclosed paragraph if any
    if curr_text_chunks or curr_p_blocks:
        streams.append(
            ParagraphStream(
                p_idx=p_idx,
                text="".join(curr_text_chunks),
                blocks=list(curr_p_blocks),
            )
        )

    return streams, all_blocks


def detect_mutations_in_part(
    part_name: str,
    xml_text: str,
    *,
    normalize_spaces: bool = False,
    aggressive_homoglyphs: bool = False,
    strip_emoji_glue: bool = False,
    strip_bidi: bool = True,
) -> list[TextCodepointMutation]:
    """Detect watermark carriers in a Word XML part using logical text streams.

    Runs canonical contextual classification over paragraph streams, bridging
    split runs and variation selectors. Returns exact TextCodepointMutation records.
    """
    streams, _ = parse_part_text_streams(xml_text)
    mutations: list[TextCodepointMutation] = []

    for stream in streams:
        if not stream.text:
            continue

        classifications = classify_stream(
            stream.text,
            normalize_spaces=normalize_spaces,
            aggressive_homoglyphs=aggressive_homoglyphs,
            strip_emoji_glue=strip_emoji_glue,
            strip_bidi=strip_bidi,
        )

        for item in classifications:
            if item.action in ("strip", "replace"):
                char_ref = stream.get_char_ref(item.offset)
                block = char_ref.block
                ch = item.char
                cp = item.codepoint
                replacement = item.out_char if item.action == "replace" else ""

                # Context witness for safety verification: +/- 15 chars around mutation
                ctx_start = max(0, item.offset - 15)
                ctx_end = min(len(stream.text), item.offset + 16)
                witness = stream.text[ctx_start:ctx_end]

                mutations.append(
                    TextCodepointMutation(
                        part_name=part_name,
                        p_idx=block.p_idx,
                        r_idx=block.r_idx,
                        t_idx=block.t_idx,
                        offset=char_ref.local_offset,
                        codepoint=cp,
                        char_name=unicodedata.name(ch, f"U+{cp:04X}"),
                        replacement=replacement,
                        logical_offset=item.offset,
                        context_witness=witness,
                        t_block_idx=block.t_block_idx,
                    )
                )

    return mutations
