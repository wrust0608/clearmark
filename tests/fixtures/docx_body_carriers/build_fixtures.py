"""Deterministic builder for ClearMark v2.1 Phase 6 DOCX body carrier and counterexample fixtures.

Generates:
- tests/fixtures/docx_body_carriers/synthetic_baseline.docx
- tests/fixtures/docx_body_carriers/carrier_zwsp.docx
- tests/fixtures/docx_body_carriers/carrier_bidi_supported.docx
- tests/fixtures/docx_body_carriers/carrier_unicode_tags.docx
- tests/fixtures/docx_body_carriers/carrier_with_non_text_children.docx
- tests/fixtures/docx_body_carriers/carrier_mixed.docx
- tests/fixtures/docx_body_carriers/counterexample_emoji_zwj.docx
- tests/fixtures/docx_body_carriers/counterexample_arabic_joiner.docx
- tests/fixtures/docx_body_carriers/counterexample_devanagari.docx
- tests/fixtures/docx_body_carriers/counterexample_nbsp.docx
- tests/fixtures/docx_body_carriers/counterexample_nfc_nfd.docx
- tests/fixtures/docx_body_carriers/carrier_and_legitimate_unicode.docx
- tests/fixtures/docx_body_carriers/MANIFEST.json
- tests/fixtures/docx_body_carriers/README.md

Provenance:
Built purely via Python standard library zipfile & xml.etree with fixed timestamps (2026-01-01 00:00:00).
Zero python-docx dependency. Zero external downloads. Deterministic SHA256 output.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

FIXTURES_DIR = Path(__file__).resolve().parent

# Fixed timestamp for reproducible zip packaging
ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def _make_zip(members: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(members.keys()):
            content = members[name]
            raw = content.encode("utf-8") if isinstance(content, str) else content
            zinfo = zipfile.ZipInfo(filename=name, date_time=ZIP_TIME)
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zinfo.create_system = 0  # FAT / Windows portable
            zf.writestr(zinfo, raw)
    return buf.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

DOC_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdHeader1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rIdFooter1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
  <Relationship Id="rIdHyperlink1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://clearmark.local" TargetMode="External"/>
</Relationships>
"""

CORE_PROPS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>ClearMark Phase 6 Synthetic Baseline</dc:title>
</cp:coreProperties>
"""

APP_PROPS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <TotalTime>1</TotalTime>
</Properties>
"""

HEADER1_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:r>
      <w:t>Header Section Title</w:t>
    </w:r>
  </w:p>
</w:hdr>
"""

FOOTER1_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:r>
      <w:t>Footer Page Details</w:t>
    </w:r>
  </w:p>
</w:ftr>
"""

BASELINE_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p>
      <w:r>
        <w:rPr><w:b/></w:rPr>
        <w:t>Document Heading</w:t>
      </w:r>
      <w:r>
        <w:t> - ClearMark Synthetic Test Document</w:t>
      </w:r>
    </w:p>
    <w:p>
      <w:r>
        <w:t xml:space="preserve">Standard paragraph text with preserved spacing. </w:t>
      </w:r>
      <w:r>
        <w:t>Secondary run in paragraph.</w:t>
      </w:r>
    </w:p>
    <w:p>
      <w:bookmarkStart w:id="0" w:name="SectionBM"/>
      <w:r>
        <w:t>Bookmarked text span</w:t>
      </w:r>
      <w:bookmarkEnd w:id="0"/>
      <w:hyperlink r:id="rIdHyperlink1">
        <w:r>
          <w:t>Linked resource</w:t>
        </w:r>
      </w:hyperlink>
    </w:p>
    <w:p>
      <w:r>
        <w:t>Before break</w:t>
        <w:br/>
        <w:tab/>
        <w:t>After tab</w:t>
        <w:br w:type="page"/>
        <w:t>New page content</w:t>
      </w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc>
          <w:p>
            <w:r><w:t>Table Row 1 Cell 1</w:t></w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:p>
            <w:r><w:t>Table Row 1 Cell 2</w:t></w:r>
          </w:p>
        </w:tc>
      </w:tr>
      <w:tr>
        <w:tc>
          <w:p>
            <w:r><w:t>Table Row 2 Cell 1</w:t></w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:p>
            <w:r><w:t>Table Row 2 Cell 2</w:t></w:r>
          </w:p>
        </w:tc>
      </w:tr>
    </w:tbl>
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rIdHeader1"/>
      <w:footerReference w:type="default" r:id="rIdFooter1"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


def _get_base_members() -> dict[str, str | bytes]:
    return {
        "[Content_Types].xml": CONTENT_TYPES_XML,
        "_rels/.rels": ROOT_RELS_XML,
        "docProps/core.xml": CORE_PROPS_XML,
        "docProps/app.xml": APP_PROPS_XML,
        "word/document.xml": BASELINE_DOCUMENT_XML,
        "word/header1.xml": HEADER1_XML,
        "word/footer1.xml": FOOTER1_XML,
        "word/_rels/document.xml.rels": DOC_RELS_XML,
    }


def build_all_fixtures() -> dict:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Base Document
    base_members = _get_base_members()
    base_bytes = _make_zip(base_members)
    base_sha256 = _sha256(base_bytes)
    (FIXTURES_DIR / "synthetic_baseline.docx").write_bytes(base_bytes)

    manifest_entries = []

    # Record baseline in manifest
    manifest_entries.append({
        "fixture_id": "synthetic_baseline",
        "filename": "synthetic_baseline.docx",
        "sha256": base_sha256,
        "source_baseline_sha256": base_sha256,
        "purpose": "Clean synthetic base document containing paragraphs, multiple runs, table, headers/footers, bookmarks, hyperlinks, and page break.",
        "inserted_codepoints": [],
        "preserved_sequences": ["xml:space='preserve'", "w:br", "w:tab", "w:br w:type='page'"],
        "expected_changed_parts": [],
        "expected_structure": {
            "paragraph_count": 8,
            "run_count": 13,
            "table_count": 1,
            "table_row_count": 2,
            "table_cell_count": 4,
            "manual_page_break_count": 1,
            "bookmark_count": 1,
            "hyperlink_count": 1
        }
    })

    # Helper to generate a fixture from modified members
    def add_fixture(fid, filename, purpose, mod_dict, inserted_cps=None, preserved_sequences=None, expected_parts=None, preserved_seqs=None):
        if preserved_sequences is None:
            preserved_sequences = preserved_seqs if preserved_seqs is not None else []
        if inserted_cps is None:
            inserted_cps = []
        if expected_parts is None:
            expected_parts = []
        mem = dict(base_members)
        mem.update(mod_dict)
        data = _make_zip(mem)
        h = _sha256(data)
        (FIXTURES_DIR / filename).write_bytes(data)
        manifest_entries.append({
            "fixture_id": fid,
            "filename": filename,
            "sha256": h,
            "source_baseline_sha256": base_sha256,
            "purpose": purpose,
            "inserted_codepoints": inserted_cps,
            "preserved_sequences": preserved_sequences,
            "expected_changed_parts": expected_parts,
            "expected_structure": {
                "paragraph_count": 8,
                "run_count": 13,
                "table_count": 1,
                "table_row_count": 2,
                "table_cell_count": 4,
                "manual_page_break_count": 1,
                "bookmark_count": 1,
                "hyperlink_count": 1
            }
        })

    # 2. carrier_zwsp.docx
    doc_zwsp = BASELINE_DOCUMENT_XML.replace(
        "<w:t> - ClearMark Synthetic Test Document</w:t>",
        "<w:t> - ClearMark\u200BSynthetic\u200BTest Document</w:t>"
    ).replace(
        "<w:t>Table Row 1 Cell 1</w:t>",
        "<w:t>Table\u200BRow 1 Cell 1</w:t>"
    )
    add_fixture(
        fid="carrier_zwsp",
        filename="carrier_zwsp.docx",
        purpose="Positive test: U+200B ZERO WIDTH SPACE carrier in paragraph run and table cell.",
        mod_dict={"word/document.xml": doc_zwsp},
        inserted_cps=[
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "paragraph 1 run 2 (offset 12)", "expected": "REMOVE"},
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "paragraph 1 run 2 (offset 22)", "expected": "REMOVE"},
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "table cell 1 (offset 5)", "expected": "REMOVE"}
        ],
        preserved_seqs=[],
        expected_parts=["word/document.xml"]
    )

    # 3. carrier_bidi_supported.docx
    doc_bidi = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>Secondary\u200Erun\u200Fin\u202Aparagraph\u202C.\u2066Embedded\u2069</w:t>"
    )
    add_fixture(
        fid="carrier_bidi_supported",
        filename="carrier_bidi_supported.docx",
        purpose="Positive test: supported bidi direction controls (LRM U+200E, RLM U+200F, LRE U+202A, PDF U+202C, LRI U+2066, PDI U+2069).",
        mod_dict={"word/document.xml": doc_bidi},
        inserted_cps=[
            {"codepoint": "U+200E", "name": "LEFT-TO-RIGHT MARK", "part": "word/document.xml", "location": "paragraph 2 run 2", "expected": "REMOVE"},
            {"codepoint": "U+200F", "name": "RIGHT-TO-LEFT MARK", "part": "word/document.xml", "location": "paragraph 2 run 2", "expected": "REMOVE"},
            {"codepoint": "U+202A", "name": "LEFT-TO-RIGHT EMBEDDING", "part": "word/document.xml", "location": "paragraph 2 run 2", "expected": "REMOVE"},
            {"codepoint": "U+202C", "name": "POP DIRECTIONAL FORMATTING", "part": "word/document.xml", "location": "paragraph 2 run 2", "expected": "REMOVE"},
            {"codepoint": "U+2066", "name": "LEFT-TO-RIGHT ISOLATE", "part": "word/document.xml", "location": "paragraph 2 run 2", "expected": "REMOVE"},
            {"codepoint": "U+2069", "name": "POP DIRECTIONAL ISOLATE", "part": "word/document.xml", "location": "paragraph 2 run 2", "expected": "REMOVE"}
        ],
        preserved_seqs=[],
        expected_parts=["word/document.xml"]
    )

    # 4. carrier_unicode_tags.docx
    doc_tags = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Bookmarked text span</w:t>",
        "<w:t>Bookmarked\U000E0001text\U000E0020span\U000E0041test\U000E007F</w:t>"
    )
    add_fixture(
        fid="carrier_unicode_tags",
        filename="carrier_unicode_tags.docx",
        purpose="Positive test: Unicode Tag characters (U+E0001, U+E0020, U+E0041, U+E007F).",
        mod_dict={"word/document.xml": doc_tags},
        inserted_cps=[
            {"codepoint": "U+E0001", "name": "LANGUAGE TAG", "part": "word/document.xml", "location": "paragraph 3 run 1", "expected": "REMOVE"},
            {"codepoint": "U+E0020", "name": "TAG SPACE", "part": "word/document.xml", "location": "paragraph 3 run 1", "expected": "REMOVE"},
            {"codepoint": "U+E0041", "name": "TAG LATIN CAPITAL LETTER A", "part": "word/document.xml", "location": "paragraph 3 run 1", "expected": "REMOVE"},
            {"codepoint": "U+E007F", "name": "CANCEL TAG", "part": "word/document.xml", "location": "paragraph 3 run 1", "expected": "REMOVE"}
        ],
        preserved_seqs=[],
        expected_parts=["word/document.xml"]
    )

    # 5. carrier_with_non_text_children.docx
    doc_non_text = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Before break</w:t>\n        <w:br/>\n        <w:tab/>\n        <w:t>After tab</w:t>\n        <w:br w:type=\"page\"/>\n        <w:t>New page content</w:t>",
        "<w:t>Before\u200Bbreak</w:t>\n        <w:br/>\n        <w:tab/>\n        <w:t>After\u200Btab</w:t>\n        <w:br w:type=\"page\"/>\n        <w:t>New\u200Bpage content</w:t>"
    )
    add_fixture(
        fid="carrier_with_non_text_children",
        filename="carrier_with_non_text_children.docx",
        purpose="Positive test: carriers adjacent to run children (w:br, w:tab, w:br w:type='page') confirming children are not dropped or reordered.",
        mod_dict={"word/document.xml": doc_non_text},
        inserted_cps=[
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "paragraph 4 run 1 (before br)", "expected": "REMOVE"},
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "paragraph 4 run 1 (after tab)", "expected": "REMOVE"},
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "paragraph 4 run 1 (after page break)", "expected": "REMOVE"}
        ],
        preserved_seqs=["w:br", "w:tab", "w:br w:type='page'"],
        expected_parts=["word/document.xml"]
    )

    # 6. carrier_mixed.docx (multi-part carriers across document, header, footer, table)
    doc_mixed = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Document Heading</w:t>",
        "<w:t>Document\u200BHead\u00ADing</w:t>"
    ).replace(
        "<w:t>Table Row 2 Cell 2</w:t>",
        "<w:t>Table\u2060Row\uFEFF2</w:t>"
    )
    hdr_mixed = HEADER1_XML.replace(
        "<w:t>Header Section Title</w:t>",
        "<w:t>Header\u200BSection Title</w:t>"
    )
    ftr_mixed = FOOTER1_XML.replace(
        "<w:t>Footer Page Details</w:t>",
        "<w:t>Footer\u200EPage Details</w:t>"
    )
    add_fixture(
        fid="carrier_mixed",
        filename="carrier_mixed.docx",
        purpose="Positive test: mixed carriers (U+200B, U+00AD, U+2060, U+FEFF, U+200E) across document body, table cells, header, and footer.",
        mod_dict={
            "word/document.xml": doc_mixed,
            "word/header1.xml": hdr_mixed,
            "word/footer1.xml": ftr_mixed
        },
        inserted_cps=[
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "document heading", "expected": "REMOVE"},
            {"codepoint": "U+00AD", "name": "SOFT HYPHEN", "part": "word/document.xml", "location": "document heading", "expected": "REMOVE"},
            {"codepoint": "U+2060", "name": "WORD JOINER", "part": "word/document.xml", "location": "table cell 4", "expected": "REMOVE"},
            {"codepoint": "U+FEFF", "name": "ZERO WIDTH NO-BREAK SPACE", "part": "word/document.xml", "location": "table cell 4", "expected": "REMOVE"},
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/header1.xml", "location": "header paragraph", "expected": "REMOVE"},
            {"codepoint": "U+200E", "name": "LEFT-TO-RIGHT MARK", "part": "word/footer1.xml", "location": "footer paragraph", "expected": "REMOVE"}
        ],
        preserved_seqs=[],
        expected_parts=["word/document.xml", "word/header1.xml", "word/footer1.xml"]
    )

    # 7. counterexample_emoji_zwj.docx
    # Legitimate emoji ZWJ sequences: Family 👨‍👩‍👧, Technologist 👩‍💻, Astronaut 👨‍🚀, Rainbow Flag 🏳️‍🌈, Heart on Fire ❤️‍🔥
    doc_emoji = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>Emoji sequence: 👨‍👩‍👧 and 👩‍💻 and 👨‍🚀 and 🏳️‍🌈 and ❤️‍🔥 intact.</w:t>"
    )
    add_fixture(
        fid="counterexample_emoji_zwj",
        filename="counterexample_emoji_zwj.docx",
        purpose="Counterexample test: legitimate emoji sequences with ZWJ U+200D (family, profession, gendered, rainbow flag, heart on fire) must be preserved exactly.",
        mod_dict={"word/document.xml": doc_emoji},
        inserted_cps=[],
        preserved_sequences=["👨‍👩‍👧", "👩‍💻", "👨‍🚀", "🏳️‍🌈", "❤️‍🔥"],
        expected_parts=[]
    )

    # 8. counterexample_arabic_joiner.docx
    # Legitimate Arabic/Persian joiners: Persian می‌روم (ZWNJ U+200C flanked by Arabic letters), Arabic word with ZWJ بـه (\u0628\u200D\u0647)
    doc_arabic = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>Persian: می‌روم and Arabic: \u0628\u200D\u0647 text sample.</w:t>"
    )
    add_fixture(
        fid="counterexample_arabic_joiner",
        filename="counterexample_arabic_joiner.docx",
        purpose="Counterexample test: legitimate Arabic/Persian orthographic joiners (ZWNJ U+200C and ZWJ U+200D in Arabic script context) must be preserved exactly.",
        mod_dict={"word/document.xml": doc_arabic},
        inserted_cps=[],
        preserved_sequences=["می‌روم", "\u0628\u200D\u0647"],
        expected_parts=[]
    )

    # 9. counterexample_devanagari.docx
    # Legitimate Devanagari conjuncts: क्‍ष (U+0915 U+094D U+200D U+0937) and क्‌ष (U+0915 U+094D U+200C U+0937)
    doc_devanagari = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>Devanagari conjuncts: क्‍ष and क्‌ष preserved.</w:t>"
    )
    add_fixture(
        fid="counterexample_devanagari",
        filename="counterexample_devanagari.docx",
        purpose="Counterexample test: legitimate Devanagari shaping conjuncts with ZWJ and ZWNJ in Indic context must be preserved exactly.",
        mod_dict={"word/document.xml": doc_devanagari},
        inserted_cps=[],
        preserved_sequences=["क्‍ष", "क्‌ष"],
        expected_parts=[]
    )

    # 10. counterexample_nbsp.docx
    # Typographic non-breaking space (U+00A0) and narrow non-breaking space (U+202F)
    doc_nbsp = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>Dimensions: 100\u00A0km and 50\u202Fkg and Page\u00A042.</w:t>"
    )
    add_fixture(
        fid="counterexample_nbsp",
        filename="counterexample_nbsp.docx",
        purpose="Counterexample test: protected typographic spaces (U+00A0 NO-BREAK SPACE and U+202F NARROW NO-BREAK SPACE) in SAFE mode must remain untouched.",
        mod_dict={"word/document.xml": doc_nbsp},
        inserted_cps=[],
        preserved_sequences=["100\u00A0km", "50\u202Fkg", "Page\u00A042"],
        expected_parts=[]
    )

    # 11. counterexample_nfc_nfd.docx
    # Vietnamese NFC (Tiếng Việt) vs NFD (Tiếng Việt)
    doc_nfc_nfd = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>NFC: Ti\u1EBFng Vi\u1EC7t vs NFD: Tie\u0302\u0301ng Vie\u0302\u0323t</w:t>"
    )
    add_fixture(
        fid="counterexample_nfc_nfd",
        filename="counterexample_nfc_nfd.docx",
        purpose="Counterexample test: NFC and NFD strings preserved in their exact representation without cross-normalization.",
        mod_dict={"word/document.xml": doc_nfc_nfd},
        inserted_cps=[],
        preserved_sequences=["Tiếng Việt", "Tiếng Việt"],
        expected_parts=[]
    )

    # 12. carrier_and_legitimate_unicode.docx (Combined Grand Test)
    doc_combined = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Document Heading</w:t>",
        "<w:t>Document\u200BHeading\u00ADwith Carriers</w:t>"
    ).replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>Emoji: 👨‍👩‍👧, Persian: می‌روم, Devanagari: क्‍ष, NBSP: 100\u00A0km, with\u200Ecarrier\U000E0020tags.</w:t>"
    )
    add_fixture(
        fid="carrier_and_legitimate_unicode",
        filename="carrier_and_legitimate_unicode.docx",
        purpose="Combined test: simultaneous presence of removable carriers (U+200B, U+00AD, U+200E, U+E0020) AND legitimate counterexamples (emoji ZWJ, Arabic ZWNJ, Devanagari ZWJ, NBSP).",
        mod_dict={"word/document.xml": doc_combined},
        inserted_cps=[
            {"codepoint": "U+200B", "name": "ZERO WIDTH SPACE", "part": "word/document.xml", "location": "heading", "expected": "REMOVE"},
            {"codepoint": "U+00AD", "name": "SOFT HYPHEN", "part": "word/document.xml", "location": "heading", "expected": "REMOVE"},
            {"codepoint": "U+200E", "name": "LEFT-TO-RIGHT MARK", "part": "word/document.xml", "location": "body paragraph", "expected": "REMOVE"},
            {"codepoint": "U+E0020", "name": "TAG SPACE", "part": "word/document.xml", "location": "body paragraph", "expected": "REMOVE"}
        ],
        preserved_sequences=["👨‍👩‍👧", "می‌روم", "क्‍ष", "100\u00A0km"],
        expected_parts=["word/document.xml"]
    )

    # 13. counterexample_same_codepoint_witness.docx (Same-codepoint negative witness)
    doc_same_cp = BASELINE_DOCUMENT_XML.replace(
        "<w:t>Secondary run in paragraph.</w:t>",
        "<w:t>Legitimate 🏳️‍🌈 and ❤️‍🔥 with Carrier\u200Dtest sample.</w:t>"
    )
    add_fixture(
        fid="counterexample_same_codepoint_witness",
        filename="counterexample_same_codepoint_witness.docx",
        purpose="Same-codepoint witness: contains legitimate ZWJ (rainbow flag 🏳️‍🌈, heart on fire ❤️‍🔥) AND an isolated suspicious carrier ZWJ (U+200D). Cleaner must remove ONLY the carrier ZWJ and preserve legitimate ZWJs.",
        mod_dict={"word/document.xml": doc_same_cp},
        inserted_cps=[
            {"codepoint": "U+200D", "name": "ZERO WIDTH JOINER", "part": "word/document.xml", "location": "body paragraph", "expected": "REMOVE"}
        ],
        preserved_sequences=["🏳️‍🌈", "❤️‍🔥"],
        expected_parts=["word/document.xml"]
    )

    manifest_data = {
        "version": "2.2.0",
        "provenance": "Generated deterministically by tests/fixtures/docx_body_carriers/build_fixtures.py",
        "baseline_document": "synthetic_baseline.docx",
        "baseline_sha256": base_sha256,
        "fixtures": manifest_entries
    }

    manifest_json_path = FIXTURES_DIR / "MANIFEST.json"
    manifest_json_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    readme_content = f"""# ClearMark v2.2 — DOCX Body-Carrier & Counterexample Fixture Corpus

**Corpus Version**: 2.2.0  
**Baseline Document**: `synthetic_baseline.docx` (SHA256: `{base_sha256}`)  
**Provenance**: Generated deterministically by `build_fixtures.py` with zero external dependencies.

## Fixture Inventory

| Fixture ID | Filename | Purpose | Category |
|---|---|---|---|
| `synthetic_baseline` | `synthetic_baseline.docx` | Clean base document without carriers | Baseline |
| `carrier_zwsp` | `carrier_zwsp.docx` | Positive: U+200B ZERO WIDTH SPACE | Positive Carrier |
| `carrier_bidi_supported` | `carrier_bidi_supported.docx` | Positive: Directional bidi controls (LRM, RLM, LRE, PDF, LRI, PDI) | Positive Carrier |
| `carrier_unicode_tags` | `carrier_unicode_tags.docx` | Positive: Unicode Tag characters (U+E0001, U+E0020, U+E0041, U+E007F) | Positive Carrier |
| `carrier_with_non_text_children` | `carrier_with_non_text_children.docx` | Positive: Carriers near w:br, w:tab, w:br page break | Non-Text Run Invariance |
| `carrier_mixed` | `carrier_mixed.docx` | Positive: Multi-part carriers (body, table, header, footer) | Multi-Part Carrier |
| `counterexample_emoji_zwj` | `counterexample_emoji_zwj.docx` | Counterexample: Legitimate emoji ZWJ sequences (👨‍👩‍👧, 👩‍💻, 👨‍🚀, 🏳️‍🌈, ❤️‍🔥) | Contextual Preservation |
| `counterexample_arabic_joiner` | `counterexample_arabic_joiner.docx` | Counterexample: Legitimate Persian/Arabic ZWNJ and ZWJ (می‌روم, بـه) | Contextual Preservation |
| `counterexample_devanagari` | `counterexample_devanagari.docx` | Counterexample: Legitimate Devanagari shaping conjuncts (क्‍ष, क्‌ष) | Contextual Preservation |
| `counterexample_nbsp` | `counterexample_nbsp.docx` | Counterexample: Protected typographic spaces (100 km, 50 kg) | Typographic Preservation |
| `counterexample_nfc_nfd` | `counterexample_nfc_nfd.docx` | Counterexample: NFC vs NFD Vietnamese text preservation | Normalization Invariance |
| `carrier_and_legitimate_unicode` | `carrier_and_legitimate_unicode.docx` | Combined: Positive carriers AND legitimate Unicode counterexamples | Combined Grand Test |
| `counterexample_same_codepoint_witness` | `counterexample_same_codepoint_witness.docx` | Witness: Legitimate ZWJ (🏳️‍🌈, ❤️‍🔥) and suspicious carrier ZWJ in same part | Negative Witness |

See `MANIFEST.json` for exact codepoint mappings and expected results.
"""
    (FIXTURES_DIR / "README.md").write_text(readme_content, encoding="utf-8")
    return manifest_data


if __name__ == "__main__":
    manifest = build_all_fixtures()
    print(f"Successfully generated {len(manifest['fixtures'])} DOCX fixtures with MANIFEST.json and README.md.")
