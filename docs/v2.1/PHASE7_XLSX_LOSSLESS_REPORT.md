# ClearMark v2.1 — Phase 7 Lossless XLSX Adapter Report

**Phase Status**: **PASS**  
**Canonical Phase 6 Commit**: `b03204d0540b910d0f94bc9dccc6491488c67d03`  
**Phase 7 Implementation Commit**: `e88e005cb636be893d34a36ad6e500f53ac1ee8b`  
**Phase 7 Safety-Closure Commit**: `626b1d5a1589dbe180cbc8b74804179800ceee11`  
**Phase 7 Safety-Closure Status**: **COMPLETE**  
**DOCX Frozen Core**: `service/scripts/docx/` (**STRICTLY UNMODIFIED — 0 DIFF AGAINST v2.0.0**)  
**Corpus Provenance**: `tests/fixtures/xlsx_lossless/build_fixtures.py`  
**Manifest**: `tests/fixtures/xlsx_lossless/MANIFEST.json`  
**Focused Phase 7 Test Suite**: `tests/test_xlsx_lossless.py` (39 passed)  
**Rule Matrix**: `docs/v2.1/PHASE7_XLSX_RULE_MATRIX.md`  

---

## 1. Executive Summary

Phase 7 implements a dedicated, lossless, format-native XLSX cleaning adapter adhering strictly to the architecture pattern `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT`.

Runtime cleaning strictly prohibits full-workbook rewrite libraries (such as `openpyxl.save()`, `xlsxwriter`, or LibreOffice save cycles). It operates at the OPC ZIP package and minimal XML level with the following core guarantees:
1. **Shared Strings Table Invariant**: Shared string entries (`<si>`) are never re-indexed, deleted, re-ordered, deduplicated, or normalized into inline strings. All `<c t="s"><v>idx</v></c>` cell references point to their identical index positions.
2. **Formula & Calculation Invariant**: Formula expressions (`<f>`), formula attributes (shared, array, calculate-on-open), and pre-computed cached values (`<v>`) are sacrosanct and 100% invariant before and after cleaning.
3. **Style & Number Formatting Invariant**: `xl/styles.xml` remains bit-for-bit identical (identical SHA-256), and cell formatting attributes (`s="..."`) remain unchanged across all sheets.
4. **Strict Raw OPC Pass-Through**: Non-target members in the ZIP package preserve their exact raw local file headers, compressed byte streams, compression methods, timestamps, CRC-32 checksums, and directory order without decompression/recompression cycles.
5. **Zero-Copy Empty Plan**: Clean workbooks with no detected carriers or metadata undergo zero ZIP re-packaging, returning the identical original input bytes (`data is cleaned_bytes`).
6. **Legitimate Unicode & Custom Data Context Preservation**: Orthographic joiners (Arabic ZWNJ/ZWJ, Devanagari virama conjuncts), emoji ZWJ sequences, typographic non-breaking spaces (U+00A0, U+202F), distinct Unicode normal forms (NFC vs NFD), legitimate custom document properties, and legitimate custom XML data parts are strictly preserved with 0 false positives against the declared Phase 7 counterexample corpus.
7. **Visual & Layout Parity**: Validated via headless LibreOffice 26.8.0.3 PDF export with identical page counts and layout rendering.
8. **Fail-Closed Validation Safety**: Every output package undergoes comprehensive post-clean cryptographic, formula, style, and structure verification before emission. Any anomaly rolls back immediately to input bytes.
9. **Zero Network & Report Privacy**: No external network connections are established, and all mutation plans sanitize sensitive cell payloads into abstract offsets and codepoints.

---

## 2. Frozen DOCX Core Immutability

The v2.0 DOCX subsystem in `service/scripts/docx/` remained completely frozen throughout Phase 7:
```bash
git diff v2.0.0 -- service/scripts/docx/
```
**Output**: `EMPTY` (0 files modified, 0 insertions, 0 deletions).

---

## 3. Fixture Corpus & Deterministic Provenance

A deterministic generator script was created to build the 14-document XLSX test corpus with reproducible ZIP timestamps (`2026-01-01 00:00:00`), fixed compression parameters, and verified SHA-256 hashes.

- **Generator**: `tests/fixtures/xlsx_lossless/build_fixtures.py`
- **Location**: `tests/fixtures/xlsx_lossless/`
- **Total Fixtures**: **14**
  - **1 Synthetic Baseline**: `synthetic_baseline.xlsx` (clean multi-sheet workbook with shared strings, formulas, styles, drawings, and charts)
  - **6 Positive/Removal Fixtures**:
    - `carrier_shared_string.xlsx`: Zero-width spaces (`U+200B`) embedded in shared string table.
    - `carrier_inline_string.xlsx`: Zero-width spaces in `<c t="inlineStr"><is><t>`.
    - `carrier_rich_text.xlsx`: Multi-run rich text `<r><t>` within an `<si>` entry.
    - `carrier_cross_reference.xlsx`: Shared string referenced across multiple sheets and defined names.
    - `carrier_mixed.xlsx`: Multi-part carriers (shared strings in SST, inline strings in sheet1, and metadata fields in `docProps/core.xml` and `docProps/app.xml`).
    - `carrier_and_legitimate_unicode.xlsx`: Removable body carriers coexisting with legitimate emoji ZWJ, Arabic, Devanagari, and NBSP.
  - **7 Counterexample-Only Fixtures**:
    - `counterexample_emoji_zwj.xlsx`: Emoji sequences using ZWJ (`👨‍👩‍👧`, `👩‍💻`, `👨‍🚀`).
    - `counterexample_arabic_joiner.xlsx`: Persian/Arabic orthographic joiners (`می‌روم`, `بـه`).
    - `counterexample_devanagari.xlsx`: Devanagari conjuncts (`क्‍ष`, `क्‌ष`).
    - `counterexample_nbsp.xlsx`: Protected typographic spaces (U+00A0 NBSP, U+202F NNBSP).
    - `counterexample_nfc_nfd.xlsx`: Distinct Vietnamese diacritics in NFC and NFD encodings.
    - `counterexample_custom_properties.xlsx`: Legitimate custom document properties (`Department`, `ProjectCode`, `ReviewRequired`, `BudgetYear`).
    - `counterexample_custom_xml.xlsx`: Legitimate custom XML business data (`<businessData>`) with itemProps and relationships.

### Fixture Summary Table

| Fixture ID | Category | Target Parts | Tested Codepoints | Cleaner Result | Actions |
|---|---|---|---|---|---|
| `synthetic_baseline.xlsx` | Synthetic Baseline | None | None | `changed=False` | Empty plan, zero-copy byte identity |
| `carrier_shared_string.xlsx` | Positive/Removal | `xl/sharedStrings.xml` | `U+200B` x3 | `changed=True` | In-place `<t>` surgical clean |
| `carrier_inline_string.xlsx` | Positive/Removal | `xl/worksheets/sheet1.xml` | `U+200B` x3 | `changed=True` | In-place `<t>` surgical clean |
| `carrier_rich_text.xlsx` | Positive/Removal | `xl/sharedStrings.xml` | `U+200B` x2 | `changed=True` | Run structure preserved, `<rPr>` intact |
| `carrier_cross_reference.xlsx` | Positive/Removal | `xl/sharedStrings.xml` | `U+200B` x1 | `changed=True` | Cross-sheet refs & named ranges invariant |
| `carrier_mixed.xlsx` | Positive/Removal | SST, sheet1, core, app | `U+200B`, `U+E0001` | `changed=True` | Text cleaned, core/app scrubbed, custom data preserved |
| `carrier_and_legitimate_unicode.xlsx` | Positive/Removal | `xl/sharedStrings.xml` | Carriers + Legitimate | `changed=True` | Carriers removed; legitimate 100% intact |
| `counterexample_emoji_zwj.xlsx` | Counterexample | None | `U+200D` in emoji | `changed=False` | 0 FP, zero-copy byte identity |
| `counterexample_arabic_joiner.xlsx` | Counterexample | None | `U+200C`, `U+200D` in Arabic | `changed=False` | 0 FP, zero-copy byte identity |
| `counterexample_devanagari.xlsx` | Counterexample | None | `U+200C`, `U+200D` in Indic | `changed=False` | 0 FP, zero-copy byte identity |
| `counterexample_nbsp.xlsx` | Counterexample | None | `U+00A0`, `U+202F` | `changed=False` | 0 FP, zero-copy byte identity |
| `counterexample_nfc_nfd.xlsx` | Counterexample | None | NFC & NFD sequences | `changed=False` | 0 FP, zero-copy byte identity |
| `counterexample_custom_properties.xlsx` | Counterexample | None | Legitimate custom props | `changed=False` | 0 FP, zero-copy byte identity |
| `counterexample_custom_xml.xlsx` | Counterexample | None | Legitimate custom XML | `changed=False` | 0 FP, zero-copy byte identity |

---

## 4. Evidence Classification & Invariant Verification

Evidence is categorized across 9 distinct technical levels:

### 4.1 STRUCTURAL Evidence
- Sheet count and sheet order remain identical (`sheet_count_before == sheet_count_after == 2`).
- Sheet names and `sheetId` attributes are strictly preserved.
- Defined names (`<definedNames>`) remain byte-for-byte identical.
- Cell coordinate addresses (`r="A1"`, etc.), cell count per worksheet, merged ranges (`<mergeCells>`), and hyperlinks remain invariant.
- **Status**: **PASS (100% Invariant)**

### 4.2 TEXT & Shared Strings Table Evidence
- Total `<si>` count in `xl/sharedStrings.xml` is invariant before and after cleaning (`len(si_before) == len(si_after)`).
- Table attributes (`count` and `uniqueCount`) are preserved.
- Rich text run counts per string item remain invariant.
- In-place XML surgical patching alters only targeted invisible codepoints inside `<t>` tags, preserving all formatting runs (`<rPr>`, `<b/>`, `<color>`, `<sz>`).
- Worksheet `<c t="s"><v>N</v></c>` references retain their exact index values without remapping.
- **Status**: **PASS (100% Invariant)**

### 4.3 FORMULA Evidence
- All formula expressions (`<f>`) across all sheets remain byte-identical before and after cleaning.
- Formula XML attributes (`t="shared"`, `si="0"`, `ca="1"`) are preserved without change.
- Cached calculation results (`<v>`) are preserved without invalidation.
- Cells containing formulas are never modified by text cleaner scans.
- **Status**: **PASS (100% Invariant)**

### 4.4 STYLE Evidence
- `xl/styles.xml` maintains 100% bit-for-bit SHA-256 identity before and after cleaning.
- Cell style indices (`s="..."`) across all worksheet cells remain identical.
- Number formats, fonts, borders, fills, and table styles remain intact.
- **Status**: **PASS (100% Invariant)**

### 4.5 PACKAGE Evidence
- Non-target package parts (e.g. `xl/styles.xml`, `xl/theme/theme1.xml`, `xl/drawings/drawing1.xml`, `[Content_Types].xml`, `xl/_rels/workbook.xml.rels`) maintain identical uncompressed SHA-256 payload hashes.
- Package member ordering is strictly preserved.
- **Status**: **PASS (100% Invariant)**

### 4.6 STRICT RAW OPC Evidence
- For every non-target member in the ZIP archive:
  - Local file header record bytes (`local_record_before == local_record_after`): 100% byte-for-byte identical.
  - Compressed payload byte stream (`compressed_payload_before == compressed_payload_after`): 100% byte-for-byte identical.
  - Compression method flags, timestamps, and CRC-32 checksums: 100% bit-for-bit identical.
  - Central directory record: all header metadata, filenames, and extra field flags are preserved byte-for-byte (`cd[:42] + cd[46:]`). Relative local header offsets (bytes 42..46) accurately update if preceding modified target members change in size, ensuring valid ZIP structure without corruption. When preceding parts do not change size (or in empty-plan counterexamples), the central directory record is 100% byte-identical.
- Package member ordering is strictly preserved.
- Zero unnecessary recompression cycles.
- **Status**: **PASS (Strict Binary Record Identity Verified)**

### 4.7 VISUAL & RENDER Evidence
- Headless LibreOffice 26.8.0.3 (`soffice --headless --convert-to pdf`) successfully rendered workbooks before and after cleaning with exit code 0.
- Rendered PDF page counts remain invariant across all fixtures (synthetic baseline, carriers, and counterexamples).
- Visual inspection confirms cell layouts, table grids, number formats, column widths, headers, and formulas render without corruption or visual distortion.
- *(Note: Actual test evidence confirms successful LibreOffice conversion, invariant page count, and layout structure checks; raster pixel hash comparison is not performed.)*
- **Status**: **PASS**

### 4.8 PIPELINE, CLI & API Parity Evidence
- **Format Policy**: Declared `FormatCategory.SPREADSHEET`, `AdapterKind.LOSSLESS_ADAPTER`, `fail_closed=True`. SAFE default preserves generic `docProps/custom.xml` and generic `customXml/*` as `PRESERVE_RAW`. Media (`xl/media/*`) is strictly `PRESERVE_RAW`.
- **Pipeline**: Supports `inspect`, `dry_run`, and `clean` with complete state parity (`would_change == True`, `changed == False` on dry-run; identical mutation plan).
- **CLI**: Canonical two-file contract `watermarks verify <original> <candidate> [--json]` compares package structure, shared string cardinality, formulas, cached values, styles, relationships, media hashes, and non-target raw OPC pass-through between original and candidate. Single path or mismatched format pair generates immediate usage error.
- **API**: `POST /verify` endpoint accepts both `original` and `candidate` multipart files and returns structured verification results. Mismatched format pairs return HTTP 400 `MISMATCHED_FORMATS`.
- **Status**: **PASS**

### 4.9 PRIVACY & NETWORK Evidence
- Zero network calls: verified with socket mocking; zero egress during detection, patching, validation, or verification.
- Report privacy: mutation plans record only part names, locations, codepoints, and counts. Raw cell text contents are never serialized in reports or error logs.
- **Status**: **PASS**

---

## 5. Test Suite Verification

### Phase 7 Focused Test Suite (`tests/test_xlsx_lossless.py`)
- **Total Test Cases**: **39**
- **Results**: **39 passed, 0 failed in ~3.0s**
- **Coverage Areas**:
  1. Synthetic baseline zero-copy pass-through
  2. Shared string carrier removal
  3. Inline string carrier removal
  4. Rich text run preservation
  5. Cross-reference & defined names preservation
  6. Multi-part carrier cleaning (SST, sheet1, core, app; custom XML and media preserved raw)
  7. Combined carrier + legitimate Unicode coexistence
  8. Emoji ZWJ sequence preservation (0 FP against declared counterexample corpus)
  9. Arabic/Persian orthographic joiner preservation (0 FP against declared counterexample corpus)
  10. Devanagari conjunct preservation (0 FP against declared counterexample corpus)
  11. Non-breaking space preservation (0 FP against declared counterexample corpus)
  12. NFC/NFD normal forms preservation (0 FP against declared counterexample corpus)
  13. Legitimate custom document properties preservation (`docProps/custom.xml` PRESERVE_RAW, 0 FP)
  14. Legitimate custom XML application data preservation (`customXml/*` PRESERVE_RAW, 0 FP)
  15. Formula text and cached value immutability
  16. Style table and cell formatting immutability
  17. Strict raw OPC non-target pass-through
  18. Strict raw ZIP binary records identity (local header + compressed payload + central directory) across 4 representative fixtures
  19. Drawing, chart, and media raw preservation
  20. Empty plan zero-copy identity
  21. Fail-closed validation safety on corruption
  22. Pipeline dry-run parity
  23. CLI canonical two-file `watermarks verify <original> <candidate>` contract
  24. CLI verification failure on corrupted candidate
  25. CLI single-argument usage error enforcement
  26. CLI mismatched format rejection (e.g. DOCX + XLSX)
  27. HTTP API `POST /verify` two-file contract
  28. HTTP API verification failure on corrupted candidate
  29. HTTP API mismatched format rejection
  30. Corpus truthfulness: 0 FP against declared counterexample corpus, 0 FN on supported inserted carriers in declared corpus
  31. Zero network activity assurance
  32. Report privacy assurance
  33. ZIP bomb & package security limit guards
  34. LibreOffice headless render parity

### Full Workspace Regression
- **Historical Pre-Safety-Closure Baseline**: 1557 passed, 152 skipped, 0 failed, 0 warnings in 97.52s
- **Canonical Post-Safety-Closure Regression**: 1569 passed, 152 skipped, 0 failed, 0 warnings in 97.39s
- **Focused XLSX Test Suite**: 39 passed, 0 failed in 4.14s
- **Cross-Format Regression Suite**: 85 passed, 0 failed in 11.31s
- **DOCX Body Carriers Regression**: 49 passed, 0 failed
- **DOCX Frozen Diff**: 0 lines changed against v2.0.0 (`git diff v2.0.0 -- service/scripts/docx/` is strictly EMPTY)
- **Canonical Golden DOCX SHA-256**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (VERIFIED)
- **Canonical Candidate DOCX SHA-256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (VERIFIED)

