"""Tests for Phase 4: Immutable Mutation Planning and Carrier Detection."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import io
import zipfile
import pytest

from service.scripts.docx.mutation_plan import (
    DocxMutationPlan,
    MetadataFieldScrubMutation,
    PartDropMutation,
    TextCodepointMutation,
    MediaScrubMutation,
)
from service.scripts.docx.package import DocxPackage
from service.scripts.docx.detector import DocxDetector, _is_safe_carrier


def test_mutation_dataclasses_are_frozen():
    """Ensure mutation dataclasses cannot be modified once instantiated (immutability)."""
    t_mut = TextCodepointMutation(
        part_name="word/document.xml",
        p_idx=0,
        r_idx=0,
        t_idx=0,
        codepoint=0x200B,
        char_name="ZERO WIDTH SPACE",
        offset=5,
    )
    with pytest.raises(FrozenInstanceError):
        t_mut.codepoint = 0x200C  # type: ignore

    m_mut = MetadataFieldScrubMutation(
        part_name="docProps/core.xml",
        tag_name="creator",
        label="dc:creator",
    )
    with pytest.raises(FrozenInstanceError):
        m_mut.label = "other"  # type: ignore

    d_mut = PartDropMutation(
        part_name="customXml/item1.xml",
        reason="customXml part",
    )
    with pytest.raises(FrozenInstanceError):
        d_mut.part_name = "docProps/custom.xml"  # type: ignore


def test_mutation_plan_changed_parts():
    """Verify changed_parts accurately tracks modified parts and relationship files."""
    plan = DocxMutationPlan()
    assert plan.is_empty()
    assert plan.changed_parts() == set()

    # Add a text mutation in document.xml
    plan.text_mutations.append(
        TextCodepointMutation(
            part_name="word/document.xml",
            p_idx=0,
            r_idx=0,
            t_idx=0,
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            offset=0,
        )
    )
    assert not plan.is_empty()
    assert plan.changed_parts() == {"word/document.xml"}

    # Add a part drop -> should automatically flag [Content_Types].xml and rels
    plan.part_drops.append(
        PartDropMutation(
            part_name="customXml/item1.xml",
            reason="provenance part",
        )
    )
    changed = plan.changed_parts()
    assert "customXml/item1.xml" in changed
    assert "[Content_Types].xml" in changed
    assert "_rels/.rels" in changed
    assert "word/_rels/document.xml.rels" in changed


def test_detector_is_deterministic():
    """Ensure DocxDetector produces 100% deterministic mutation plans on identical inputs."""
    doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p>
          <w:r><w:t>Hello\u200BWorld\uFEFFTest</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>"""

    core_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                       xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:creator>Author A</dc:creator>
      <cp:lastModifiedBy>Editor B</cp:lastModifiedBy>
    </cp:coreProperties>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("docProps/core.xml", core_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")

    data = buf.getvalue()
    pkg1 = DocxPackage(data)
    plan1 = DocxDetector(pkg1, {"mode": "SAFE"}).build_plan()

    pkg2 = DocxPackage(data)
    plan2 = DocxDetector(pkg2, {"mode": "SAFE"}).build_plan()

    assert plan1.to_dict() == plan2.to_dict()
    assert len(plan1.text_mutations) == 2  # U+200B and U+FEFF
    assert len(plan1.metadata_mutations) == 2  # creator and lastModifiedBy


def test_emoji_sequence_protection():
    """Verify emoji sequences (ZWJ joining family members and VS16 variation selectors) are protected."""
    # 👨‍👩‍👧 = U+1F468 (man) + U+200D (ZWJ) + U+1F469 (woman) + U+200D (ZWJ) + U+1F467 (girl)
    man = 0x1F468
    zwj = 0x200D
    woman = 0x1F469
    girl = 0x1F467

    # ZWJ between man and woman must NOT be flagged as safe carrier
    assert not _is_safe_carrier(zwj, prev_cp=man, next_cp=woman)
    assert not _is_safe_carrier(zwj, prev_cp=woman, next_cp=girl)

    # Isolated ZWJ without emoji or complex script MUST be flagged as carrier
    assert _is_safe_carrier(zwj, prev_cp=ord("A"), next_cp=ord("B"))

    # ❤️ = U+2764 (heart) + U+FE0F (emoji variation selector)
    heart = 0x2764
    vs16 = 0xFE0F
    assert not _is_safe_carrier(vs16, prev_cp=heart)

    # Isolated VS16 after ASCII text MUST be flagged
    assert _is_safe_carrier(vs16, prev_cp=ord("X"))


def test_complex_script_protection():
    """Verify ZWNJ/ZWJ in Arabic or Indic scripts are protected from false-positive removal."""
    # Arabic sample: Ba + ZWJ + Ta
    ba = 0x0628
    zwj = 0x200D
    ta = 0x062A
    assert not _is_safe_carrier(zwj, prev_cp=ba, next_cp=ta)

    # Devanagari sample: Ka + Virama + ZWJ
    ka = 0x0915
    ra = 0x0930
    assert not _is_safe_carrier(zwj, prev_cp=ka, next_cp=ra)


def test_app_props_protection():
    """Verify app.xml preserves AppVersion and TotalTime while targeting Company and Application."""
    app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
      <Application>Microsoft Office Word</Application>
      <AppVersion>16.0000</AppVersion>
      <TotalTime>45</TotalTime>
      <Company>Secret Corp</Company>
      <Pages>19</Pages>
    </Properties>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body/></w:document>")
        zf.writestr("docProps/app.xml", app_xml)
        zf.writestr("[Content_Types].xml", "<Types/>")

    pkg = DocxPackage(buf.getvalue())
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    scrubbed_tags = [m.tag_name for m in plan.metadata_mutations]
    assert "Application" in scrubbed_tags
    assert "Company" in scrubbed_tags
    assert "AppVersion" not in scrubbed_tags
    assert "TotalTime" not in scrubbed_tags
    assert "Pages" not in scrubbed_tags
