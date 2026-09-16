# Phase 7 XLSX Package Part Rule Matrix

This document provides the authoritative classification of Open Packaging Convention (OPC) parts within XLSX workbooks for ClearMark v2.1 Phase 7.

## Classification Policy

Each part within an XLSX workbook is classified into exactly one of five operational categories:

1. **`CLEAN_TEXT`**: The part contains visible, user-facing text payload subject to carrier detection and minimal in-place removal. All non-text markup, node structure, XML attributes, and run hierarchies are strictly preserved.
2. **`CLEAN_METADATA`**: The part contains document provenance or extended/custom metadata properties subject to metadata scrubbing (emptying tracking fields, removing custom tracking properties) or removal when verified.
3. **`PRESERVE_RAW`**: The part is non-target. It must remain byte-identical and raw-preserved (uncompressed SHA256, compressed payload bytes, CRC, ZipInfo flags, timestamps, external/internal attributes, extra fields, and comment identical).
4. **`NOT_CHECKED`**: The part is neither scanned nor mutated in Phase 7. It is preserved raw byte-for-byte.
5. **`UNSUPPORTED`**: The part or container feature cannot be proven lossless under Phase 7 rules; detection triggers immediate fail-closed rejection.

---

## OPC Part Classification Matrix

| Part URI / Pattern | Category | Description | Phase 7 Treatment & Invariants |
|---|---|---|---|
| `xl/sharedStrings.xml` | `CLEAN_TEXT` | Shared String Table (`<sst>`) | Minimal in-place patch of targeted `<t>` elements only. `<si>` count, `uniqueCount`, and `<si>` entry ordering are strictly preserved. Never reindexed or rebuilt. Rich text runs `<r>` and formatting `<rPr>` preserved. |
| `xl/worksheets/sheet*.xml` (inline strings) | `CLEAN_TEXT` | Worksheet cell inline strings (`<c t="inlineStr"><is><t>`) | Minimal in-place patch of targeted `<t>` elements inside `<is>`. Rich text runs `<is><r><t>` preserved. Cell coordinates, types, and styles invariant. |
| `xl/worksheets/sheet*.xml` (formula nodes `<f>`) | `PRESERVE_RAW` | Worksheet cell formulas | **SACROSANCT**. Zero character removal inside `<f>`. Formula text, attributes (`t="shared"`, `ref`, `si`), and cached values (`<v>`) are preserved codepoint-for-codepoint. |
| `xl/worksheets/sheet*.xml` (structure & non-target cells) | `PRESERVE_RAW` | Rows, columns, numbers, dates, booleans, errors | Cell references, row numbers, dimensions, merged ranges (`<mergeCells>`), data validations, hyperlinks, page setups remain exact. |
| `docProps/core.xml` | `CLEAN_METADATA` | Dublin Core & OpenXML Core Properties | Empties provenance tracking fields (`dc:creator`, `cp:lastModifiedBy`, `dc:description`). Preserves `dc:title`, timestamps, and XML structure. Classified as metadata scrubbing, not confirmed AI watermark removal. |
| `docProps/app.xml` | `CLEAN_METADATA` | Extended Properties | Empties `Application` and `Company`. Preserves `AppVersion`, `TotalTime`, `HeadingPairs`, `TitlesOfParts`. |
| `docProps/custom.xml` (generic custom properties) | `PRESERVE_RAW` | Custom Document Properties | **PRESERVED RAW BY DEFAULT**. Arbitrary user/application properties (e.g. Department, ProjectCode, BudgetYear) are not watermarks and are preserved bit-for-bit. |
| `docProps/custom.xml` (recognized provenance marker) | `CLEAN_METADATA` | Recognized Provenance Property | Scrubbed/dropped only if an explicit high-confidence provenance marker signature is identified. (No such signatures active in Phase 7 SAFE mode). |
| `customXml/*` (generic custom XML) | `PRESERVE_RAW` / `NOT_CHECKED` | Custom XML Data Storage parts | **PRESERVED RAW BY DEFAULT**. Arbitrary business data, schema definitions, and custom datastore items are preserved bit-for-bit. |
| `customXml/*` (recognized provenance marker) | `CLEAN_METADATA` | Provenance Custom XML parts | Only mutated or dropped when a concrete, high-confidence detector identifies a supported provenance signature. |
| `xl/workbook.xml` | `PRESERVE_RAW` | Workbook Definition | Preserves sheet count, sheet names, sheet IDs, sheet order, relationship IDs, defined names (`<definedNames>`), view settings, and calculation properties. |
| `xl/styles.xml` | `PRESERVE_RAW` | Spreadsheet Formatting & Styles | **PRESERVED BYTE-IDENTICAL**. Raw SHA256 invariant. Fonts, fills, borders, cellXfs, cellStyleXfs, and number formats are never rebuilt or normalized. |
| `xl/calcChain.xml` | `PRESERVE_RAW` | Calculation Order Chain | Preserved byte-identical. |
| `xl/theme/theme*.xml` | `PRESERVE_RAW` | Theme Definitions | Preserved byte-identical. |
| `xl/drawings/drawing*.xml` | `PRESERVE_RAW` | Worksheet Drawing Definitions | Preserved byte-identical. |
| `xl/media/*` | `PRESERVE_RAW` | Embedded Images / Media | Preserved byte-identical (raw payload and hashes). Workbook image cleaning is an orthogonal concern. |
| `xl/charts/chart*.xml` | `PRESERVE_RAW` | Chart Definitions | Preserved byte-identical. |
| `xl/externalLinks/*` | `PRESERVE_RAW` | External Workbook References | Preserved byte-identical. |
| `xl/pivotTables/*` | `PRESERVE_RAW` | Pivot Table Definitions | Preserved byte-identical. |
| `xl/pivotCache/*` | `PRESERVE_RAW` | Pivot Cache Definitions | Preserved byte-identical. |
| `xl/comments*.xml` | `NOT_CHECKED` | Legacy Cell Comments / Notes | Not checked for carriers in Phase 7; preserved byte-identical. |
| `xl/threadedComments/*` | `NOT_CHECKED` | Modern Threaded Comments | Not checked for carriers in Phase 7; preserved byte-identical. |
| `xl/persons/person.xml` | `NOT_CHECKED` | Threaded Comment Person Entities | Not checked for carriers in Phase 7; preserved byte-identical. |
| `xl/worksheets/sheet*.xml` (`<headerFooter>`) | `NOT_CHECKED` | Worksheet Headers & Footers | Not checked for carriers in Phase 7; preserved byte-identical. |
| `_rels/.rels`, `xl/_rels/*` | `PRESERVE_RAW` | Package and Part Relationships | Preserved byte-identical by default. Dangling reference pruning occurs only if a recognized provenance part is intentionally dropped. |
| `[Content_Types].xml` | `PRESERVE_RAW` | Package Content Types | Preserved byte-identical by default. Override pruning occurs only if a recognized provenance part is intentionally dropped. |
| `xl/vbaProject.bin` | `UNSUPPORTED` | Macro-Enabled Workbook Code | Rejects mutation fail-closed. |
| `xl/signature/*` | `UNSUPPORTED` | Digital Signatures | Rejects mutation fail-closed to prevent invalidating cryptographic signatures. |
| Multi-disk ZIP / Encrypted ZIP | `UNSUPPORTED` | Unsupported Packaging Features | Rejects immediately fail-closed. |

---

## Contextual Unicode Preservation Rules

In accordance with Phase 6 established principles, the XLSX text scanner enforces:
1. **Emoji ZWJ Sequences**: Sequences containing `U+200D` between emoji characters are recognized and preserved.
2. **Arabic/Persian Joiners**: Orthographic `U+200C` (ZWNJ) and `U+200D` (ZWJ) in valid phonetic/orthographic contexts are preserved.
3. **Devanagari / Indic Conjuncts**: Halant-adjacent joiners forming ligatures are preserved.
4. **Typographic Spaces**: Non-breaking spaces (`U+00A0` NBSP, `U+202F` NNBSP) are strictly preserved in `SAFE` mode.
5. **Normalization**: Canonical NFC/NFD distinctions are preserved; no automated Unicode normalizations are forced.
