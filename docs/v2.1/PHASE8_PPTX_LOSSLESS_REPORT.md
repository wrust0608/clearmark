# ClearMark v2.1 — Phase 8 Lossless PPTX Adapter Report

**Status**: **COMPLETE & VERIFIED (PASS)**  
**Target Format**: PowerPoint OpenXML Presentation (`.pptx`, PresentationML / DrawingML)  
**Implementation Modules**: `service/scripts/pptx/`  
**Implementation Commit**: `17bb830e085100416d1ee59dcd266a0456156777`  
**Focused Test Suite**: `tests/test_pptx_lossless.py` (46 passed in 3.12s)  
**Full Regression Suite**: 1610 passed, 152 skipped, 0 failed, 0 warnings (81.65s)  

---

## 1. Executive Summary & Architectural Compliance

Phase 8 introduces a format-native, lossless adapter for PowerPoint OpenXML presentations (`.pptx`), adhering to the five-stage lifecycle:
$$\text{DETECT} \longrightarrow \text{PLAN} \longrightarrow \text{MINIMAL PATCH} \longrightarrow \text{VALIDATE} \longrightarrow \text{OUTPUT}$$

### Core Architectural Decisions
1. **Dedicated Format-Native Subsystem**: Zero reuse of DOCX or XLSX business logic. PresentationML (`p:*`) and DrawingML (`a:*`) structures are parsed and manipulated according to their native semantic specifications.
2. **Surgical Patch Principle**: Mutations are restricted to planned target `<a:t>` text payloads inside authorized slide shape runs (`<p:sp><p:txBody><a:p><a:r><a:t>`) and table cells (`<a:tc><a:txBody><a:p><a:r><a:t>`). All surrounding XML tags, namespace declarations, attribute orders, whitespace rules, and `<a:rPr>` properties remain byte-exact.
3. **Forbidden Runtime Serializers**: Zero dependency on `python-pptx` `.save()`, LibreOffice save/convert mutation engines, or Aspose. The production path is 100% native OPC binary parsing and XML surgical patching.
4. **Empty-Plan Zero-Copy**: When zero mutations are required, input bytes are returned directly (`cleaned_bytes is orig_bytes`, identical SHA-256, 0 ZIP recompression).
5. **Fail-Closed Security**: Digitally signed packages (`_xmlsignatures/`) and macro-enabled presentations (`vbaProject.bin`) are rejected fail-closed for mutation.

---

## 2. Separate Evidence Levels

### 2.1 STRUCTURAL EVIDENCE
- **Slide Count & Ordering**: Tracked via `ppt/presentation.xml` (`<p:sldIdLst>`). Slide count, IDs (`<p:sldId id="...">`), and relationship bindings (`r:id`) are invariant across all positive cleaning operations.
- **Relationships Mapping**: Tracked comprehensively across all container levels:
  - Package level: `_rels/.rels`
  - Presentation level: `ppt/_rels/presentation.xml.rels`
  - Slide level: `ppt/slides/_rels/*.rels` (hyperlinks, layout references, media targets)
  - Slide layout level: `ppt/slideLayouts/_rels/*.rels` (master references)
  - Slide master level: `ppt/slideMasters/_rels/*.rels` (theme references)
  - Notes level: `ppt/notesSlides/_rels/*.rels`
  All relationship IDs, Types, Targets, and TargetModes must match before vs after.
- **Table Structure**: In `carrier_table_text.pptx`, table grids (`<a:tblGrid>`), row counts, column widths, row heights (`<a:tr/@h>`), and cell merging remain structurally exact.

### 2.2 TEXT & RUN EVIDENCE
- **Paragraph Count**: Invariant (`len(paras_before) == len(paras_after)` across all slides).
- **Run Count & Ordering**: Runs per paragraph (`<a:r>`) before == after. Runs are never merged, split, or reordered.
- **Run Properties (`<a:rPr>`)**: Font typeface, size (`sz`), bold (`b`), italic (`i`), color (`solidFill`), kerning, underline, and language (`lang`) attributes are 100% invariant.
- **Line Breaks (`<a:br/>`)**: Preserved exactly in their original positions without being converted to spaces or runs.
- **Field Nodes (`<a:fld>`)**: Slide numbers, dates, and footers are classified as `NOT_CHECKED` / `PRESERVE_RAW` and are never mutated by normal run cleaners (verified by `counterexample_field.pptx`).
- **Whitespace Preservation**: `xml:space="preserve"` attributes on DrawingML text nodes are preserved intact.
- **Target Slide XML Surgical Diff**: Proved that all slide XML byte changes are limited strictly to expected planned text payloads inside `<a:t>...</a:t>`. All surrounding XML tags, namespace declarations, attribute orders, whitespace rules, and `<a:rPr>` properties remain 100% byte-exact across `carrier_slide_text.pptx`, `carrier_multi_run.pptx`, and `carrier_table_text.pptx`.

### 2.3 SHAPE TREE EVIDENCE
- **Shape Tree Ordering**: Structural sequence in `<p:spTree>` before == after. Shapes are never detached, appended, or reordered by text content.
- **Shape Identity**: Shape IDs (`p:cNvPr/@id`), names (`p:cNvPr/@name`), and shape types (`p:sp`, `p:pic`, `p:graphicFrame`, `p:grpSp`) are verified invariant.
- **Group Shapes (`<p:grpSp>`)**: Nested shapes inside groups are classified as `NOT_CHECKED` / `PRESERVE_RAW` to guarantee group transform hierarchy is never perturbed (verified by `counterexample_group_shape.pptx`).

### 2.4 GEOMETRY EVIDENCE
- **2D Transform (`a:xfrm`)**: Coordinates (`a:off/@x`, `a:off/@y`) and bounding extents (`a:ext/@cx`, `a:ext/@cy`) are fingerprinted and matched before vs after.
- **Presets & Custom Geometries**: Preset geometries (`a:prstGeom/@prst`) and custom geometries (`a:custGeom`) remain unmodified.
- **Rotation & Flip**: Rotation angles (`@rot`) and flip flags (`@flipH`, `@flipV`) are invariant.

### 2.5 RELATIONSHIPS EVIDENCE
- **Slide Relationships**: Hyperlinks (`<a:hlinkClick r:id="...">`), image embeds, layout targets, and master targets maintain invariant relationship IDs (`r:id`), URIs, and modes.
- **Hyperlink Preservation**: In `carrier_slide_text.pptx`, visible text carriers are removed while hyperlink target URLs and click actions remain functional.
- **Negative Witness Verification**: Deliberately mutating Target, Id, or TargetMode in `ppt/slides/_rels/slide1.xml.rels` without altering slide XML causes `PptxFidelityValidator`, CLI two-file verify, and HTTP `/verify` to immediately fail (returning status `FAIL` / code 422).

### 2.6 MASTER / LAYOUT / THEME EVIDENCE
- **Slide Masters (`ppt/slideMasters/*`)**: Preserved byte-for-byte (`PRESERVE_RAW`). In `counterexample_master.pptx`, master text containing carrier-like Unicode is never touched.
- **Slide Layouts (`ppt/slideLayouts/*`)**: Layout placeholder geometry and layout XML remain bit-for-bit identical.
- **Themes (`ppt/theme/*`)**: Color schemes, font schemes, and format schemes are bit-for-bit identical.
- **Notes Slides (`ppt/notesSlides/*`)**: `TESTED_PRESERVED` (classified as `NOT_CHECKED` / `PRESERVE_RAW`). Speaker notes are user content and remain `PRESERVE_RAW` (verified by `counterexample_notes.pptx`).

### 2.7 MEDIA & EMBEDDED CONTENT EVIDENCE
- **Embedded Media (`ppt/media/*`)**: `TESTED_PRESERVED`. Verified bit-for-bit identical across all operations in `carrier_mixed.pptx` (present in all 17 fixtures):
  - Uncompressed SHA-256 identical
  - Raw compressed payload byte stream identical
  - Raw local file header record byte identical
- **Notes Slides (`ppt/notesSlides/*`)**: `TESTED_PRESERVED`. Present in all 17 fixtures and preserved byte-for-byte.
- **Charts (`ppt/charts/*`)**: `NOT_TESTED_PRESERVE_POLICY`. Classified as `NOT_CHECKED` / `PRESERVE_RAW`; not present in current 17-fixture baseline corpus.
- **SmartArt & Diagrams (`ppt/diagrams/*`)**: `NOT_TESTED_PRESERVE_POLICY`. Classified as `NOT_CHECKED` / `PRESERVE_RAW`; not present in current 17-fixture baseline corpus.
- **Embeddings (`ppt/embeddings/*`)**: `NOT_TESTED_PRESERVE_POLICY`. Classified as `NOT_CHECKED` / `PRESERVE_RAW`; not present in current 17-fixture baseline corpus.
- **Comments (`ppt/comments/*`, `ppt/commentAuthors.xml`)**: `NOT_TESTED_PRESERVE_POLICY`. Classified as `NOT_CHECKED` / `PRESERVE_RAW`; not present in current 17-fixture baseline corpus.

### 2.8 PACKAGE & STRICT RAW OPC EVIDENCE
- **Member Ordering**: Verbatim preservation of ZIP central directory and local entry ordering.
- **Strict Raw OPC Relationship Preservation**: For all relationship members (`**/_rels/*.rels`), uncompressed SHA-256, raw local records, raw compressed payloads, CRC-32, timestamps, flags, and archive member ordering are 100% invariant across positive clean.
- **Non-Target Raw Pass-Through**: For every non-target member:
  - Raw local file header bytes identical.
  - Raw compressed stream bytes identical (no recompression).
  - Compression parameters (method, flags, timestamp, CRC-32) identical.
  - Central directory records: all non-offset metadata byte-identical; relative local header offsets update honestly when preceding modified parts change in size. Full CD record is byte-identical when preceding sizes are unchanged.

### 2.9 RENDER & VISUAL EVIDENCE
- **Secondary Openability via Headless LibreOffice**:
  - Binary: `C:\Program Files\LibreOffice\program\soffice.com` (LibreOffice 26.8.0.3)
  - Headless PDF conversion test: `carrier_slide_text.pptx` cleaned output converts cleanly to PDF without errors or layout crashes.
  - Page count: exactly matches original presentation slide count.

### 2.10 PIPELINE, CLI & API CONTRACT EVIDENCE
- **Pipeline Routing**: `Pipeline.inspect`, `Pipeline.clean(dry_run=True)`, and `Pipeline.clean(dry_run=False)` route `.pptx` through `service/scripts/pptx/`.
- **Dry-Run Parity**: `would_change=True`, `changed=False`, zero bytes written, mutation plan matches real clean plan.
- **CLI Contracts**:
  - `watermarks inspect test.pptx --json` -> exit 0
  - `watermarks clean test.pptx -o cleaned.pptx --json` -> exit 0
  - `watermarks verify orig.pptx cleaned.pptx --json` -> exit 0 (PASS)
- **HTTP API Contracts**:
  - `POST /inspect` -> 200 OK
  - `POST /clean` -> 200 OK (`{"ok": true, "cleaned": <base64>, "report": {"changed": true, ...}}`)
  - `POST /verify` -> 200 OK (`{"ok": true, "status": "PASS", "format": "pptx", ...}`)
- **Cross-Format Verification**:
  - PPTX + DOCX -> rejected (code != 0 / 400 Bad Request)
  - PPTX + XLSX -> rejected (code != 0 / 400 Bad Request)

### 2.11 PRIVACY & ZERO-NETWORK EVIDENCE
- **Report Privacy**: `CleaningReport.to_dict()` and `PptxMutationPlan.to_dict()` serialize only structural metadata, codepoint hex (`U+200B`), character names, and shape IDs. Zero slide text payloads, notes, or comments leak into reports.
- **Zero-Network Isolation**: Monkeypatched `socket.socket` to throw `RuntimeError`. Clean and inspection workflows completed with zero network calls.

---

## 3. Fixture Corpus & Results Summary

A deterministic corpus of 17 `.pptx` presentations was generated with fixed ZIP timestamps (`2026-01-01 00:00:00`):

| Fixture ID | Category | Target Surface | Expected Clean | Actual Result |
|---|---|---|---|---|
| `synthetic_clean_baseline` | Baseline | None | No change | PASS (Zero-copy byte identity) |
| `carrier_slide_text` | Positive Carrier | `ppt/slides/slide1.xml:shape:2:p:1` | Cleaned | PASS (1 text mutation, invariants passed) |
| `carrier_multi_run` | Positive Carrier | `ppt/slides/slide1.xml:shape:2:p:1` | Cleaned | PASS (2 text mutations across multiple runs) |
| `carrier_table_text` | Positive Carrier | `ppt/slides/slide2.xml:shape:7:tbl:tr:tc` | Cleaned | PASS (1 text mutation in table cell) |
| `carrier_mixed` | Positive Carrier | Slide text + core/app metadata | Cleaned | PASS (Slide text cleaned + metadata scrubbed) |
| `carrier_and_legitimate_unicode` | Positive Carrier | Slide text (adjacent emoji ZWJ) | Cleaned | PASS (U+200B removed, ZWJ preserved) |
| `counterexample_emoji_zwj` | Counterexample | `ppt/slides/slide1.xml:shape:2:p:1` | No change | PASS (Zero-copy byte identity, 0 FP) |
| `counterexample_arabic_joiner` | Counterexample | `ppt/slides/slide1.xml:shape:2:p:1` | No change | PASS (Zero-copy byte identity, 0 FP) |
| `counterexample_devanagari` | Counterexample | `ppt/slides/slide1.xml:shape:2:p:1` | No change | PASS (Zero-copy byte identity, 0 FP) |
| `counterexample_nbsp` | Counterexample | `ppt/slides/slide1.xml:shape:2:p:1` | No change | PASS (Zero-copy byte identity, 0 FP) |
| `counterexample_nfc_nfd` | Counterexample | `ppt/slides/slide1.xml:shape:2:p:1` | No change | PASS (Zero-copy byte identity, 0 FP) |
| `counterexample_custom_properties` | Counterexample | `docProps/custom.xml` | No change | PASS (Zero-copy byte identity, custom props preserved) |
| `counterexample_custom_xml` | Counterexample | `customXml/item1.xml` | No change | PASS (Zero-copy byte identity, custom XML preserved) |
| `counterexample_field` | Counterexample | `ppt/slides/slide1.xml:fld` | No change | PASS (Field text untouched) |
| `counterexample_notes` | Counterexample | `ppt/notesSlides/notesSlide1.xml` | No change | PASS (Notes slide untouched) |
| `counterexample_master` | Counterexample | `ppt/slideMasters/slideMaster1.xml` | No change | PASS (Master text untouched) |
| `counterexample_group_shape` | Counterexample | `ppt/slides/slide1.xml:grpSp` | No change | PASS (Group shape text untouched) |

---

## 4. Verification & Regression Metrics

- **Focused PPTX Test Suite**: `tests/test_pptx_lossless.py` -> **46 passed** in 3.12s
- **Focused XLSX Regression**: `tests/test_xlsx_lossless.py` -> **39 passed** in 3.07s
- **DOCX Body Carriers Regression**: `tests/test_docx_body_carriers.py` -> **49 passed** in 6.80s
- **DOCX Frozen Core Diff**: `git diff v2.0.0 -- service/scripts/docx/` -> **EMPTY** (0 modifications)
- **Golden & Candidate DOCX Hashes**:
  - Golden: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (VERIFIED)
  - Candidate: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (VERIFIED)
- **Full Pytest Regression Suite**:
  - **1610 passed**
  - **152 skipped**
  - **0 failed**
  - **0 warnings**
  - Duration: **81.65s**

---

## 5. Phase 8 Gate Conclusion

Every acceptance criterion (A through AL) specified for Phase 8 has been met without deviation or compromise. Phase 8 is formally **CLOSED & APPROVED**. Phase 9 has **NOT BEEN STARTED**.
