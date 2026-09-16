#!/usr/bin/env python3
"""Deterministic generator for Phase 8 PPTX Lossless Fixture Corpus.

Generates 17 reproducible PPTX presentations with fixed timestamps (2026-01-01 00:00:00),
known SHA-256 hashes, and structured classification metadata.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

FIXTURES_DIR = Path(__file__).resolve().parent
FIXED_DATETIME = (2026, 1, 1, 0, 0, 0)

# Minimal 1x1 PNG for embedded drawing/media
MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00"
    b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _create_zip_package(parts: dict[str, bytes | str]) -> bytes:
    """Build a deterministic ZIP archive with fixed timestamps and member ordering."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(parts.keys()):
            data = parts[name]
            raw = data.encode("utf-8") if isinstance(data, str) else data
            info = zipfile.ZipInfo(name, date_time=FIXED_DATETIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0  # Windows / FAT compatibility
            info.external_attr = 0o644 << 16
            zf.writestr(info, raw)
    return buf.getvalue()


def _base_presentation_parts(
    *,
    slide1_text1: str = "Presentation Title",
    slide1_text2: str = "Subtitle Here",
    slide1_body: str = "First regular body run. ",
    slide1_link: str = "Clickable Link",
    slide1_field: str = "1",
    slide1_group: str = "Grouped shape text",
    slide2_table: tuple[str, str, str, str] = ("Header A", "Header B", "Cell 1", "Cell 2"),
    slide3_text: str = "Conclusion Slide",
    notes_text: str = "Speaker note text here.",
    master_text: str = "",
    creator: str = "",
    app: str = "",
    description: str = "",
    extra_parts: dict[str, bytes | str] | None = None,
) -> dict[str, bytes | str]:
    """Generate the full dictionary of parts for a PPTX presentation."""
    parts: dict[str, bytes | str] = {}

    # [Content_Types].xml
    parts["[Content_Types].xml"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide3.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

    # _rels/.rels
    parts["_rels/.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

    # docProps/core.xml
    core_fields = ["<dc:title>Test Presentation</dc:title>"]
    if creator:
        core_fields.append(f"<dc:creator>{creator}</dc:creator>")
        core_fields.append(f"<cp:lastModifiedBy>{creator}</cp:lastModifiedBy>")
    if description:
        core_fields.append(f"<dc:description>{description}</dc:description>")

    parts["docProps/core.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
  {''.join(core_fields)}
</cp:coreProperties>"""

    # docProps/app.xml
    app_fields = ["<TotalTime>1</TotalTime>", "<Words>25</Words>"]
    if app:
        app_fields.insert(0, f"<Application>{app}</Application>")
        app_fields.insert(1, "<Company>ClearMark</Company>")

    parts["docProps/app.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  {''.join(app_fields)}
</Properties>"""

    # ppt/presentation.xml
    parts["ppt/presentation.xml"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId4"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
    <p:sldId id="257" r:id="rId2"/>
    <p:sldId id="258" r:id="rId3"/>
  </p:sldIdLst>
  <p:sldSz cx="9144000" cy="6858000" type="screen4x3"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""

    # ppt/_rels/presentation.xml.rels
    parts["ppt/_rels/presentation.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide3.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
</Relationships>"""

    # ppt/theme/theme1.xml
    parts["ppt/theme/theme1.xml"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme">
  <a:themeElements>
    <a:clrScheme name="Office">
      <a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1F497D"/></a:dk2>
      <a:lt2><a:srgbClr val="EEECE1"/></a:lt2>
      <a:accent1><a:srgbClr val="4F81BD"/></a:accent1>
      <a:accent2><a:srgbClr val="F79646"/></a:accent2>
      <a:accent3><a:srgbClr val="9BBB59"/></a:accent3>
      <a:accent4><a:srgbClr val="8064A2"/></a:accent4>
      <a:accent5><a:srgbClr val="4BACC6"/></a:accent5>
      <a:accent6><a:srgbClr val="F79646"/></a:accent6>
      <a:hlink><a:srgbClr val="0000FF"/></a:hlink>
      <a:folHlink><a:srgbClr val="800080"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Office">
      <a:majorFont><a:latin typeface="Calibri"/></a:majorFont>
      <a:minorFont><a:latin typeface="Calibri"/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="Office">
      <a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>
      <a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
      <a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
      <a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>"""

    # ppt/slideMasters/slideMaster1.xml
    master_extra_sp = ""
    if master_text:
        master_extra_sp = f"""<p:sp>
        <p:nvSpPr><p:cNvPr id="9" name="Master Shape"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100000" cy="100000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{master_text}</a:t></a:r></a:p></p:txBody>
      </p:sp>"""

    parts["ppt/slideMasters/slideMaster1.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:grpSpPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
      {master_extra_sp}
    </p:spTree>
  </p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649" r:id="rId1"/>
  </p:sldLayoutIdLst>
</p:sldMaster>"""

    # ppt/slideMasters/_rels/slideMaster1.xml.rels
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

    # ppt/slideLayouts/slideLayout1.xml
    parts["ppt/slideLayouts/slideLayout1.xml"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" type="title" preserve="1">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:grpSpPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

    # ppt/slideLayouts/_rels/slideLayout1.xml.rels
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

    # ppt/media/image1.png
    parts["ppt/media/image1.png"] = MINIMAL_PNG

    # ppt/slides/slide1.xml
    parts["ppt/slides/slide1.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:grpSpPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Title Shape"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="685800" y="609600"/><a:ext cx="7772400" cy="1143000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr b="1" lang="en-US" sz="4000"><a:solidFill><a:srgbClr val="1F497D"/></a:solidFill></a:rPr>
              <a:t>{slide1_text1}</a:t>
            </a:r>
            <a:br/>
            <a:r>
              <a:rPr i="1" lang="en-US" sz="2400"/>
              <a:t>{slide1_text2}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="3" name="Body Shape"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="685800" y="2000000"/><a:ext cx="7772400" cy="2000000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="1800"/>
              <a:t>{slide1_body}</a:t>
            </a:r>
            <a:r>
              <a:rPr b="1" lang="en-US" sz="1800">
                <a:hlinkClick r:id="rId2"/>
              </a:rPr>
              <a:t>{slide1_link}</a:t>
            </a:r>
            <a:fld id="{{D64E61CF-8526-4EDC-8A95-6E5336E2DEAE}}" type="slidenum">
              <a:rPr lang="en-US"/>
              <a:t>{slide1_field}</a:t>
            </a:fld>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:pic>
        <p:nvPicPr><p:cNvPr id="4" name="Picture 1"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
        <p:blipFill>
          <a:blip r:embed="rId3"/>
          <a:stretch><a:fillRect/></a:stretch>
        </p:blipFill>
        <p:spPr>
          <a:xfrm><a:off x="685800" y="4200000"/><a:ext cx="1000000" cy="1000000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
      </p:pic>
      <p:grpSp>
        <p:nvGrpSpPr><p:cNvPr id="5" name="Group Shape 1"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
        <p:grpSpPr>
          <a:xfrm><a:off x="3000000" y="4200000"/><a:ext cx="2000000" cy="1000000"/><a:chOff x="3000000" y="4200000"/><a:chExt cx="2000000" cy="1000000"/></a:xfrm>
        </p:grpSpPr>
        <p:sp>
          <p:nvSpPr><p:cNvPr id="6" name="Child Shape 1"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
          <p:spPr>
            <a:xfrm><a:off x="3000000" y="4200000"/><a:ext cx="2000000" cy="1000000"/></a:xfrm>
            <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          </p:spPr>
          <p:txBody>
            <a:bodyPr/>
            <a:lstStyle/>
            <a:p>
              <a:r><a:t>{slide1_group}</a:t></a:r>
            </a:p>
          </p:txBody>
        </p:sp>
      </p:grpSp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""

    # ppt/slides/_rels/slide1.xml.rels
    parts["ppt/slides/_rels/slide1.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
</Relationships>"""

    # ppt/slides/slide2.xml (Table)
    parts["ppt/slides/slide2.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:grpSpPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:graphicFrame>
        <p:nvGraphicFramePr><p:cNvPr id="7" name="Table 1"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
        <p:xfrm><a:off x="685800" y="1000000"/><a:ext cx="6000000" cy="3000000"/></p:xfrm>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
            <a:tbl>
              <a:tblPr/>
              <a:tblGrid>
                <a:gridCol w="3000000"/>
                <a:gridCol w="3000000"/>
              </a:tblGrid>
              <a:tr h="1000000">
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{slide2_table[0]}</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{slide2_table[1]}</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
              </a:tr>
              <a:tr h="1000000">
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{slide2_table[2]}</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
                <a:tc>
                  <a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{slide2_table[3]}</a:t></a:r></a:p></a:txBody>
                  <a:tcPr/>
                </a:tc>
              </a:tr>
            </a:tbl>
          </a:graphicData>
        </a:graphic>
      </p:graphicFrame>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""

    # ppt/slides/_rels/slide2.xml.rels
    parts["ppt/slides/_rels/slide2.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""

    # ppt/slides/slide3.xml (Conclusion)
    parts["ppt/slides/slide3.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:grpSpPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="8" name="Conclusion Shape"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="685800" y="609600"/><a:ext cx="7772400" cy="1143000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:r><a:t>{slide3_text}</a:t></a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""

    # ppt/slides/_rels/slide3.xml.rels
    parts["ppt/slides/_rels/slide3.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""

    # ppt/notesSlides/notesSlide1.xml
    parts["ppt/notesSlides/notesSlide1.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:grpSpPr/></p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Notes Text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="685800" y="685800"/><a:ext cx="5486400" cy="5486400"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p>
            <a:r><a:t>{notes_text}</a:t></a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:notes>"""

    # ppt/notesSlides/_rels/notesSlide1.xml.rels
    parts["ppt/notesSlides/_rels/notesSlide1.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="../slides/slide1.xml"/>
</Relationships>"""

    # Extra parts if any
    if extra_parts:
        parts.update(extra_parts)

    return parts


def build_all_fixtures(target_dir: Path | None = None) -> dict[str, dict]:
    """Generate all 17 fixtures, write .pptx files, and return manifest records."""
    dest_dir = target_dir or FIXTURES_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}

    fixtures_def = [
        # 1. Baseline Clean Presentation
        {
            "id": "synthetic_clean_baseline",
            "category": "baseline",
            "target_codepoints": [],
            "target_surface": "none",
            "expected_clean": False,
            "parts_args": {},
        },
        # 2. Positive: Carrier in slide text
        {
            "id": "carrier_slide_text",
            "category": "positive_carrier",
            "target_codepoints": ["U+200B"],
            "target_surface": "ppt/slides/slide1.xml:shape:2:p:1:r:1",
            "expected_clean": True,
            "parts_args": {
                "slide1_text1": "Presentation\u200b Title",
            },
        },
        # 3. Positive: Multi-run carriers
        {
            "id": "carrier_multi_run",
            "category": "positive_carrier",
            "target_codepoints": ["U+200B", "U+200C"],
            "target_surface": "ppt/slides/slide1.xml:shape:2:multiple_runs",
            "expected_clean": True,
            "parts_args": {
                "slide1_text1": "Presentation\u200b Title",
                "slide1_text2": "Subtitle\u200c Here",
            },
        },
        # 4. Positive: Table text carrier
        {
            "id": "carrier_table_text",
            "category": "positive_carrier",
            "target_codepoints": ["U+200B"],
            "target_surface": "ppt/slides/slide2.xml:shape:7:tbl:tr:tc",
            "expected_clean": True,
            "parts_args": {
                "slide2_table": ("Header\u200b A", "Header B", "Cell 1", "Cell 2"),
            },
        },
        # 5. Positive: Mixed slide text and metadata targets
        {
            "id": "carrier_mixed",
            "category": "positive_carrier",
            "target_codepoints": ["U+200B"],
            "target_surface": "ppt/slides/slide1.xml + docProps/core.xml + docProps/app.xml",
            "expected_clean": True,
            "parts_args": {
                "slide1_text1": "Presentation\u200b Title",
                "slide2_table": ("Header\u200b A", "Header B", "Cell 1", "Cell 2"),
                "creator": "AuthorName",
                "app": "Microsoft PowerPoint",
            },
        },
        # 6. Positive: Carrier alongside legitimate Unicode
        {
            "id": "carrier_and_legitimate_unicode",
            "category": "positive_carrier",
            "target_codepoints": ["U+200B"],
            "target_surface": "ppt/slides/slide1.xml:shape:2:p:1",
            "expected_clean": True,
            "parts_args": {
                "slide1_text1": "Hello \U0001F468\u200D\U0001F469\u200D\U0001F466\u200b World",
            },
        },
        # 7. Counterexample: Emoji ZWJ sequence
        {
            "id": "counterexample_emoji_zwj",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slides/slide1.xml:shape:2:p:1",
            "expected_clean": False,
            "parts_args": {
                "slide1_text1": "Family \U0001F468\u200D\U0001F469\u200D\U0001F466 and Technologist \U0001F469\u200D\U0001F4BB",
            },
        },
        # 8. Counterexample: Arabic joiners
        {
            "id": "counterexample_arabic_joiner",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slides/slide1.xml:shape:2:p:1",
            "expected_clean": False,
            "parts_args": {
                "slide1_text1": "فصل\u200cنامه علمی",  # Persian ZWNJ
            },
        },
        # 9. Counterexample: Devanagari
        {
            "id": "counterexample_devanagari",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slides/slide1.xml:shape:2:p:1",
            "expected_clean": False,
            "parts_args": {
                "slide1_text1": "नमस्ते भारत",
            },
        },
        # 10. Counterexample: Non-breaking space
        {
            "id": "counterexample_nbsp",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slides/slide1.xml:shape:2:p:1",
            "expected_clean": False,
            "parts_args": {
                "slide1_text1": "100\u00A0USD and 50\u202Fkg",
            },
        },
        # 11. Counterexample: NFC / NFD normalization
        {
            "id": "counterexample_nfc_nfd",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slides/slide1.xml:shape:2:p:1",
            "expected_clean": False,
            "parts_args": {
                "slide1_text1": "Cafe\u0301 and Noe\u0308l",  # NFD combining accents
            },
        },
        # 12. Counterexample: Custom document properties
        {
            "id": "counterexample_custom_properties",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "docProps/custom.xml",
            "expected_clean": False,
            "parts_args": {
                "extra_parts": {
                    "docProps/custom.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="ProjectCode"><vt:lpwstr>PRJ-999</vt:lpwstr></property>
</Properties>""",
                },
            },
        },
        # 13. Counterexample: Custom XML
        {
            "id": "counterexample_custom_xml",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "customXml/item1.xml",
            "expected_clean": False,
            "parts_args": {
                "extra_parts": {
                    "customXml/item1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><root><id>999</id></root>""",
                },
            },
        },
        # 14. Counterexample: Field text (Rule 7, 65)
        {
            "id": "counterexample_field",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slides/slide1.xml:fld",
            "expected_clean": False,
            "parts_args": {
                "slide1_field": "1\u200b",
            },
        },
        # 15. Counterexample: Speaker notes text (Rule 21, 64)
        {
            "id": "counterexample_notes",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/notesSlides/notesSlide1.xml",
            "expected_clean": False,
            "parts_args": {
                "notes_text": "Secret note with \u200b carrier",
            },
        },
        # 16. Counterexample: Slide master text (Rule 19, 63)
        {
            "id": "counterexample_master",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slideMasters/slideMaster1.xml",
            "expected_clean": False,
            "parts_args": {
                "master_text": "Master template text \u200b",
            },
        },
        # 17. Counterexample: Grouped shape text (Rule 14)
        {
            "id": "counterexample_group_shape",
            "category": "counterexample",
            "target_codepoints": [],
            "target_surface": "ppt/slides/slide1.xml:grpSp",
            "expected_clean": False,
            "parts_args": {
                "slide1_group": "Grouped text with \u200b carrier",
            },
        },
    ]

    for fdef in fixtures_def:
        fid = fdef["id"]
        filename = f"{fid}.pptx"
        parts = _base_presentation_parts(**fdef["parts_args"])
        raw_bytes = _create_zip_package(parts)
        sha256 = hashlib.sha256(raw_bytes).hexdigest()

        target_file = dest_dir / filename
        target_file.write_bytes(raw_bytes)

        manifest[fid] = {
            "fixture_id": fid,
            "filename": filename,
            "sha256": sha256,
            "category": fdef["category"],
            "target_codepoints": fdef["target_codepoints"],
            "target_surface": fdef["target_surface"],
            "expected_clean": fdef["expected_clean"],
            "expected_changed_parts": (
                ["ppt/slides/slide1.xml"]
                if fid in ("carrier_slide_text", "carrier_multi_run", "carrier_and_legitimate_unicode")
                else ["ppt/slides/slide2.xml"]
                if fid == "carrier_table_text"
                else ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml", "docProps/core.xml", "docProps/app.xml"]
                if fid == "carrier_mixed"
                else []
            ),
        }

    manifest_path = dest_dir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    records = build_all_fixtures()
    print(f"Successfully generated {len(records)} deterministic PPTX fixtures.")
