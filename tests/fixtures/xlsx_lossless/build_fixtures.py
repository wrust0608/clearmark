#!/usr/bin/env python3
"""Deterministic generator for Phase 7 XLSX Lossless Fixture Corpus.

Generates 12 reproducible XLSX workbooks with fixed timestamps (2026-01-01 00:00:00),
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


def _base_package_parts(
    *,
    shared_strings: list[str | list[tuple[str, str]]],
    sheet1_cells_xml: str,
    sheet2_cells_xml: str = '<row r="1"><c r="A1" t="inlineStr"><is><t>Sheet2 Data</t></is></c></row>',
    creator: str = "",
    app: str = "",
    description: str = "",
    extra_parts: dict[str, bytes | str] | None = None,
) -> dict[str, bytes | str]:
    """Generate the full dictionary of parts for an XLSX workbook."""
    parts: dict[str, bytes | str] = {}

    # [Content_Types].xml
    parts["[Content_Types].xml"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

    # _rels/.rels
    parts["_rels/.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

    # docProps/core.xml
    core_fields = ["<dc:title>Test Workbook</dc:title>"]
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
    app_fields = ["<TotalTime>1</TotalTime>", "<AppVersion>16.0300</AppVersion>"]
    if app:
        app_fields.insert(0, f"<Application>{app}</Application>")
        app_fields.insert(1, "<Company>ClearMark</Company>")

    parts["docProps/app.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  {''.join(app_fields)}
</Properties>"""

    # xl/workbook.xml
    parts["xl/workbook.xml"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
    <sheet name="Sheet2" sheetId="2" r:id="rId2"/>
  </sheets>
  <definedNames>
    <definedName name="SampleNamedRange">Sheet1!$A$1:$B$5</definedName>
  </definedNames>
</workbook>"""

    # xl/_rels/workbook.xml.rels
    parts["xl/_rels/workbook.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    # xl/styles.xml
    parts["xl/styles.xml"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
  </cellXfs>
</styleSheet>"""

    # Build xl/sharedStrings.xml
    si_entries: list[str] = []
    for item in shared_strings:
        if isinstance(item, str):
            si_entries.append(f"<si><t>{item}</t></si>")
        elif isinstance(item, list):
            # Rich text run: list of (formatting_tag, text)
            runs = []
            for rpr, txt in item:
                rpr_xml = f"<rPr>{rpr}</rPr>" if rpr else ""
                runs.append(f"<r>{rpr_xml}<t>{txt}</t></r>")
            si_entries.append(f"<si>{''.join(runs)}</si>")

    sst_count = len(si_entries)
    parts["xl/sharedStrings.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{sst_count}" uniqueCount="{sst_count}">
  {''.join(si_entries)}
</sst>"""

    # xl/worksheets/sheet1.xml
    parts["xl/worksheets/sheet1.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <cols>
    <col min="1" max="1" width="18" customWidth="1"/>
    <col min="2" max="2" width="24" customWidth="1"/>
  </cols>
  <sheetData>
    {sheet1_cells_xml}
  </sheetData>
  <mergeCells count="1">
    <mergeCell ref="E1:F2"/>
  </mergeCells>
  <hyperlinks>
    <hyperlink ref="A10" r:id="rIdH1"/>
  </hyperlinks>
</worksheet>"""

    # xl/worksheets/sheet2.xml
    parts["xl/worksheets/sheet2.xml"] = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {sheet2_cells_xml}
  </sheetData>
</worksheet>"""

    # xl/worksheets/_rels/sheet1.xml.rels
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdH1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/>
</Relationships>"""

    # Optional extra parts
    if extra_parts:
        parts.update(extra_parts)

    return parts


def build_all_fixtures() -> dict[str, dict]:
    """Generate all 12 fixtures deterministically and return manifest metadata."""
    manifest_entries: dict[str, dict] = {}

    # 1. Baseline Fixture
    # Includes: shared strings, rich shared string, inline string, formula, number formatting, styles, merge, hyperlink
    baseline_cells = """
    <row r="1" ht="22" customHeight="1">
      <c r="A1" t="s" s="1"><v>0</v></c>
      <c r="B1"><v>100</v></c>
      <c r="C1"><f>SUM(B1:B2)</f><v>150</v></c>
      <c r="D1" t="inlineStr"><is><t>Inline Clean</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>1</v></c>
      <c r="B2"><v>50</v></c>
      <c r="C2" t="b"><v>1</v></c>
      <c r="D2" s="2"><v>45000</v></c>
    </row>
    <row r="10">
      <c r="A10" t="inlineStr"><is><t>Hyperlink Target</t></is></c>
    </row>
    """
    baseline_sst = [
        "Quarterly Financial Summary",
        [("<b/>", "Confidential"), ("", " - Internal Use Only")],
    ]
    baseline_parts = _base_package_parts(
        shared_strings=baseline_sst,
        sheet1_cells_xml=baseline_cells,
        extra_parts={"xl/media/image1.png": MINIMAL_PNG},
    )
    # Update [Content_Types].xml for png
    baseline_bytes = _create_zip_package(baseline_parts)
    p_base = FIXTURES_DIR / "synthetic_baseline.xlsx"
    p_base.write_bytes(baseline_bytes)
    manifest_entries["synthetic_baseline"] = {
        "filename": "synthetic_baseline.xlsx",
        "category": "baseline",
        "description": "Clean 2-sheet workbook with shared strings, inline string, rich text, formula, styles, merged range, and hyperlink",
        "tested_codepoints": [],
        "expected_mutations": 0,
        "sha256": hashlib.sha256(baseline_bytes).hexdigest(),
    }

    # 2. Positive: Carrier in Shared String
    # U+200B ZERO WIDTH SPACE in shared string 0
    p_sst = [
        "Quarterly\u200bFinancial Summary",
        [("<b/>", "Confidential"), ("", " - Internal Use Only")],
    ]
    parts_sst = _base_package_parts(shared_strings=p_sst, sheet1_cells_xml=baseline_cells)
    bytes_sst = _create_zip_package(parts_sst)
    (FIXTURES_DIR / "carrier_shared_string.xlsx").write_bytes(bytes_sst)
    manifest_entries["carrier_shared_string"] = {
        "filename": "carrier_shared_string.xlsx",
        "category": "positive_carrier",
        "description": "U+200B carrier embedded inside xl/sharedStrings.xml <si><t>",
        "tested_codepoints": ["U+200B"],
        "expected_mutations": 1,
        "sha256": hashlib.sha256(bytes_sst).hexdigest(),
    }

    # 3. Positive: Carrier in Inline String
    # U+200C ZERO WIDTH NON-JOINER in worksheet inline string <c t="inlineStr"><is><t>
    inline_cells = baseline_cells.replace("Inline Clean", "Inline\u200cClean")
    parts_inline = _base_package_parts(shared_strings=baseline_sst, sheet1_cells_xml=inline_cells)
    bytes_inline = _create_zip_package(parts_inline)
    (FIXTURES_DIR / "carrier_inline_string.xlsx").write_bytes(bytes_inline)
    manifest_entries["carrier_inline_string"] = {
        "filename": "carrier_inline_string.xlsx",
        "category": "positive_carrier",
        "description": "U+200C carrier embedded inside sheet1.xml inline string <is><t>",
        "tested_codepoints": ["U+200C"],
        "expected_mutations": 1,
        "sha256": hashlib.sha256(bytes_inline).hexdigest(),
    }

    # 4. Positive: Carrier in Rich Text Run
    # U+200D ZERO WIDTH JOINER in run 1 of rich text <si><r><t>
    rich_sst = [
        "Quarterly Financial Summary",
        [("<b/>", "Confidential\u200d"), ("", " - Internal Use Only")],
    ]
    parts_rich = _base_package_parts(shared_strings=rich_sst, sheet1_cells_xml=baseline_cells)
    bytes_rich = _create_zip_package(parts_rich)
    (FIXTURES_DIR / "carrier_rich_text.xlsx").write_bytes(bytes_rich)
    manifest_entries["carrier_rich_text"] = {
        "filename": "carrier_rich_text.xlsx",
        "category": "positive_carrier",
        "description": "U+200D carrier embedded inside rich text run <si><r><t>",
        "tested_codepoints": ["U+200D"],
        "expected_mutations": 1,
        "sha256": hashlib.sha256(bytes_rich).hexdigest(),
    }

    # 5. Positive: Carrier in Cross-Referenced Shared String
    # Multiple cells reference shared string 0 which contains U+200B
    xref_cells = """
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="s"><v>0</v></c>
      <c r="C1" t="s"><v>0</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>1</v></c>
      <c r="B2"><v>42</v></c>
    </row>
    """
    xref_sst = [
        "Shared\u200bMetric",
        "Other String",
    ]
    parts_xref = _base_package_parts(shared_strings=xref_sst, sheet1_cells_xml=xref_cells)
    bytes_xref = _create_zip_package(parts_xref)
    (FIXTURES_DIR / "carrier_cross_reference.xlsx").write_bytes(bytes_xref)
    manifest_entries["carrier_cross_reference"] = {
        "filename": "carrier_cross_reference.xlsx",
        "category": "positive_carrier",
        "description": "Multiple cells (A1, B1, C1) reference the same shared string index containing U+200B",
        "tested_codepoints": ["U+200B"],
        "expected_mutations": 1,
        "sha256": hashlib.sha256(bytes_xref).hexdigest(),
    }

    # 6. Positive: Mixed Carriers across Shared Strings, Inline Strings, and Metadata
    mixed_cells = baseline_cells.replace("Inline Clean", "Inline\u200bClean")
    mixed_sst = [
        "Mixed\u200bCarriers",
        [("<b/>", "Confidential\U000E0001Tag"), ("", " - Active")],
    ]
    mixed_extras = {
        "customXml/item1.xml": "<customProps><ai>true</ai></customProps>",
        "docProps/custom.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties">
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="AIModel"><vt:lpwstr xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">GPT-4</vt:lpwstr></property>
</Properties>""",
    }
    parts_mixed = _base_package_parts(
        shared_strings=mixed_sst,
        sheet1_cells_xml=mixed_cells,
        creator="ChatGPT",
        app="Microsoft 365 Copilot",
        description="Generated by AI",
        extra_parts=mixed_extras,
    )
    # Add relationship for customXml and custom.xml in _rels/.rels and [Content_Types].xml
    parts_mixed["[Content_Types].xml"] = parts_mixed["[Content_Types].xml"].replace(
        "</Types>",
        '  <Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>\n  <Override PartName="/customXml/item1.xml" ContentType="application/xml"/>\n</Types>',
    )
    parts_mixed["_rels/.rels"] = parts_mixed["_rels/.rels"].replace(
        "</Relationships>",
        '  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/>\n  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="customXml/item1.xml"/>\n</Relationships>',
    )
    bytes_mixed = _create_zip_package(parts_mixed)
    (FIXTURES_DIR / "carrier_mixed.xlsx").write_bytes(bytes_mixed)
    manifest_entries["carrier_mixed"] = {
        "filename": "carrier_mixed.xlsx",
        "category": "positive_carrier",
        "description": "Carriers across shared strings, inline string, rich text, core.xml, app.xml, customXml, and custom.xml",
        "tested_codepoints": ["U+200B", "U+E0001"],
        "expected_mutations": 7,
        "sha256": hashlib.sha256(bytes_mixed).hexdigest(),
    }

    # 7. Positive: Carrier with Legitimate Unicode
    # U+200B carrier alongside family emoji ZWJ, Arabic joiner, Devanagari, and NBSP
    legit_sst = [
        "Salary\u200b 100\u00a0000\u202feuros",
        "Emoji: 👨‍👩‍👧‍👦 and Persian: می‌روم and Hindi: क्‍ष",
    ]
    parts_legit = _base_package_parts(shared_strings=legit_sst, sheet1_cells_xml=baseline_cells)
    bytes_legit = _create_zip_package(parts_legit)
    (FIXTURES_DIR / "carrier_and_legitimate_unicode.xlsx").write_bytes(bytes_legit)
    manifest_entries["carrier_and_legitimate_unicode"] = {
        "filename": "carrier_and_legitimate_unicode.xlsx",
        "category": "positive_carrier",
        "description": "Carrier U+200B alongside legitimate emoji ZWJ, Persian ZWNJ, Devanagari conjuncts, and NBSP",
        "tested_codepoints": ["U+200B"],
        "expected_mutations": 1,
        "sha256": hashlib.sha256(bytes_legit).hexdigest(),
    }

    # 8. Counterexample: Emoji ZWJ Sequence
    # Family emoji sequence: 👨‍👩‍👧‍👦 (U+1F468 U+200D U+1F469 U+200D U+1F467 U+200D U+1F466)
    emoji_sst = ["Family Emoji: 👨‍👩‍👧‍👦"]
    parts_emoji = _base_package_parts(shared_strings=emoji_sst, sheet1_cells_xml=baseline_cells)
    bytes_emoji = _create_zip_package(parts_emoji)
    (FIXTURES_DIR / "counterexample_emoji_zwj.xlsx").write_bytes(bytes_emoji)
    manifest_entries["counterexample_emoji_zwj"] = {
        "filename": "counterexample_emoji_zwj.xlsx",
        "category": "counterexample",
        "description": "Legitimate emoji ZWJ sequence (U+200D in 👨‍👩‍👧‍👦); expected zero mutations",
        "tested_codepoints": ["U+200D (in emoji sequence)"],
        "expected_mutations": 0,
        "sha256": hashlib.sha256(bytes_emoji).hexdigest(),
    }

    # 9. Counterexample: Arabic / Persian Orthographic Joiner (ZWNJ)
    # Persian text: می‌روم (U+0645 U+06CC U+200C U+0631 U+0648 U+0645)
    persian_sst = ["Persian Text: می‌روم"]
    parts_persian = _base_package_parts(shared_strings=persian_sst, sheet1_cells_xml=baseline_cells)
    bytes_persian = _create_zip_package(parts_persian)
    (FIXTURES_DIR / "counterexample_arabic_joiner.xlsx").write_bytes(bytes_persian)
    manifest_entries["counterexample_arabic_joiner"] = {
        "filename": "counterexample_arabic_joiner.xlsx",
        "category": "counterexample",
        "description": "Legitimate Persian orthographic ZWNJ (U+200C in می‌روم); expected zero mutations",
        "tested_codepoints": ["U+200C (in Persian text)"],
        "expected_mutations": 0,
        "sha256": hashlib.sha256(bytes_persian).hexdigest(),
    }

    # 10. Counterexample: Devanagari Halant Conjunct
    # Hindi text: क्‍ष (U+0915 U+094D U+200D U+0937)
    hindi_sst = ["Devanagari Conjunct: क्‍ष"]
    parts_hindi = _base_package_parts(shared_strings=hindi_sst, sheet1_cells_xml=baseline_cells)
    bytes_hindi = _create_zip_package(parts_hindi)
    (FIXTURES_DIR / "counterexample_devanagari.xlsx").write_bytes(bytes_hindi)
    manifest_entries["counterexample_devanagari"] = {
        "filename": "counterexample_devanagari.xlsx",
        "category": "counterexample",
        "description": "Legitimate Devanagari halant conjunct (U+200D in क्‍ष); expected zero mutations",
        "tested_codepoints": ["U+200D (in Devanagari text)"],
        "expected_mutations": 0,
        "sha256": hashlib.sha256(bytes_hindi).hexdigest(),
    }

    # 11. Counterexample: Non-Breaking Spaces (NBSP & NNBSP)
    # French typographic spacing: 10 000 euros with U+00A0 and U+202F
    nbsp_sst = ["French Spacing: 10\u00a0000\u202feuros"]
    parts_nbsp = _base_package_parts(shared_strings=nbsp_sst, sheet1_cells_xml=baseline_cells)
    bytes_nbsp = _create_zip_package(parts_nbsp)
    (FIXTURES_DIR / "counterexample_nbsp.xlsx").write_bytes(bytes_nbsp)
    manifest_entries["counterexample_nbsp"] = {
        "filename": "counterexample_nbsp.xlsx",
        "category": "counterexample",
        "description": "Typographic spaces (U+00A0 NBSP and U+202F NNBSP); expected zero mutations in SAFE mode",
        "tested_codepoints": ["U+00A0", "U+202F"],
        "expected_mutations": 0,
        "sha256": hashlib.sha256(bytes_nbsp).hexdigest(),
    }

    # 12. Counterexample: Distinct NFC vs NFD Encodings
    # Accented e: NFC (\u00e9) vs NFD (e\u0301)
    norm_sst = ["NFC: \u00e9 and NFD: e\u0301"]
    parts_norm = _base_package_parts(shared_strings=norm_sst, sheet1_cells_xml=baseline_cells)
    bytes_norm = _create_zip_package(parts_norm)
    (FIXTURES_DIR / "counterexample_nfc_nfd.xlsx").write_bytes(bytes_norm)
    manifest_entries["counterexample_nfc_nfd"] = {
        "filename": "counterexample_nfc_nfd.xlsx",
        "category": "counterexample",
        "description": "Distinct NFC (U+00E9) and NFD (U+0065 U+0301) encodings preserved without forced normalization",
        "tested_codepoints": ["U+00E9", "U+0301"],
        "expected_mutations": 0,
        "sha256": hashlib.sha256(bytes_norm).hexdigest(),
    }

    # Write MANIFEST.json
    manifest_path = FIXTURES_DIR / "MANIFEST.json"
    manifest_data = {
        "corpus_name": "xlsx_lossless",
        "version": "2.1.0",
        "fixed_timestamp": "2026-01-01T00:00:00Z",
        "fixture_count": len(manifest_entries),
        "fixtures": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    # Write README.md
    readme_path = FIXTURES_DIR / "README.md"
    readme_content = f"""# Phase 7 XLSX Lossless Fixture Corpus

Deterministic synthetic test fixtures for the ClearMark v2.1 XLSX Lossless Adapter.

## Provenance
- Generator: `build_fixtures.py`
- Fixed Archive Timestamp: `2026-01-01 00:00:00`
- Compression: `ZIP_DEFLATED` level 9
- Total Fixtures: `{len(manifest_entries)}`

## Fixture Inventory

| Fixture ID | Filename | Category | Description | Tested Codepoints | Expected Mutations |
|---|---|---|---|---|---|
"""
    for fid, item in manifest_entries.items():
        cps = ", ".join(item["tested_codepoints"]) if item["tested_codepoints"] else "None"
        readme_content += f"| `{fid}` | `{item['filename']}` | `{item['category']}` | {item['description']} | `{cps}` | `{item['expected_mutations']}` |\n"

    readme_path.write_text(readme_content, encoding="utf-8")
    return manifest_entries


if __name__ == "__main__":
    manifest = build_all_fixtures()
    print(f"Generated {len(manifest)} XLSX fixtures deterministically in {FIXTURES_DIR}")
