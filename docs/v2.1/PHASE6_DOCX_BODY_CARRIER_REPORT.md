# ClearMark v2.1 — Phase 6 DOCX Body-Carrier & Contextual Preservation Report

**Phase Status**: **PASS**  
**Canonical Phase 5 Commit**: `ce07215b00234cf16f3c18e36ec570168ac57de5`  
**Phase 6 Implementation Commit**: `3c0ee4349505a97185e3aa5bd615296e6c6ecc31`  
**DOCX Frozen Core**: `service/scripts/docx/` (**STRICTLY UNMODIFIED — 0 DIFF AGAINST v2.0.0**)  
**Corpus Provenance**: `tests/fixtures/docx_body_carriers/build_fixtures.py`  
**Manifest**: `tests/fixtures/docx_body_carriers/MANIFEST.json`  
**Focused Phase 6 Test Suite**: `tests/test_docx_body_carriers.py` (49 passed)  
**Pre-Micro-Audit Full Regression**: 1525 passed, 152 skipped, 0 failed, 0 warnings (71.48s)  

---

## 1. Executive Summary

Phase 6 provides rigorous cryptographic, structural, strict raw OPC, and fixture-specific rendering evidence demonstrating that the existing frozen DOCX subsystem in `service/scripts/docx/`:
1. **Detects real invisible body carriers** within OOXML text nodes across paragraphs, multiple runs, table cells, headers, and footers.
2. **Plans only intended minimal mutations** without phantom actions or ungrounded alterations.
3. **Removes supported carriers in-place** inside existing `<w:t>` nodes without deleting runs or dropping non-text elements.
4. **Preserves legitimate contextual Unicode** (emoji ZWJ sequences, Arabic/Persian orthographic joiners, Devanagari shaping conjuncts, typographic non-breaking spaces, and NFC/NFD distinct encodings) with zero corruption.
5. **Preserves structural and layout invariants**:
   - `run_count_before == run_count_after` across all 12 fixtures;
   - Invariant paragraph, table, row, cell, page-break, tab, bookmark, and hyperlink counts;
   - Non-text run children (`<w:br/>`, `<w:tab/>`, `<w:br w:type="page"/>`) remain in their exact sequence;
   - `xml:space="preserve"` attributes and whitespace boundaries remain intact.
6. **Preserves non-target OPC ZIP package members** under strict raw binary preservation (uncompressed SHA256, compressed bytes SHA256, CRC, flags, compression method, timestamps, and member ordering identical).
7. **Demonstrates fixture-specific layout preservation** via headless LibreOffice 26.8.0.3 rendering (identical page counts across all fixtures, 100% pixel identity on baseline and counterexamples).
8. **Maintains complete fidelity with zero network activity and zero report privacy leakage**.

---

## 2. Frozen DOCX Core Immutability

The DOCX core under test remained strictly immutable throughout Phase 6:
```bash
git diff v2.0.0 -- service/scripts/docx/
```
**Output**: `EMPTY` (0 lines changed, 0 files modified).

All tests, fixtures, and verifications were executed exclusively against the frozen v2.0 implementation without any core modifications or monkeypatch workarounds.

---

## 3. Fixture Corpus & Deterministic Provenance

A deterministic generator script was created to build the 12-document test corpus with reproducible ZIP timestamps (`2026-01-01 00:00:00`), fixed compression levels, and verified SHA256 hashes.

- **Generator**: `tests/fixtures/docx_body_carriers/build_fixtures.py`
- **Location**: `tests/fixtures/docx_body_carriers/`
- **Total Fixtures**: **12**
  - **1 Synthetic Baseline**: `synthetic_baseline.docx`
  - **6 Positive/Removal Fixtures**: `carrier_zwsp.docx`, `carrier_bidi_supported.docx`, `carrier_unicode_tags.docx`, `carrier_with_non_text_children.docx`, `carrier_mixed.docx`, `carrier_and_legitimate_unicode.docx`
  - **5 Counterexample-Only Fixtures**: `counterexample_emoji_zwj.docx`, `counterexample_arabic_joiner.docx`, `counterexample_devanagari.docx`, `counterexample_nbsp.docx`, `counterexample_nfc_nfd.docx`

### Fixture Inventory & Classification Matrix

| Fixture ID | Filename | Category | Purpose | Tested Codepoints | Cleaner Result |
|---|---|---|---|---|---|
| `synthetic_baseline` | `synthetic_baseline.docx` | Synthetic Baseline | Clean base document with multi-run paragraphs, table, header/footer, bookmark, hyperlink, and manual page break | None | `changed=False`, 0 mutations |
| `carrier_zwsp` | `carrier_zwsp.docx` | Positive/Removal | U+200B ZERO WIDTH SPACE carrier in body run and table cell | `U+200B` x3 | `changed=True`, 3 removed |
| `carrier_bidi_supported` | `carrier_bidi_supported.docx` | Positive/Removal | Supported directional bidi controls | `U+200E`, `U+200F`, `U+202A`, `U+202C`, `U+2066`, `U+2069` | `changed=True`, 6 removed |
| `carrier_unicode_tags` | `carrier_unicode_tags.docx` | Positive/Removal | Unicode Tag characters outside emoji flags | `U+E0001`, `U+E0020`, `U+E0041`, `U+E007F` | `changed=True`, 4 removed |
| `carrier_with_non_text_children` | `carrier_with_non_text_children.docx` | Positive/Removal | Carrier text adjacent to `<w:br/>`, `<w:tab/>`, and `<w:br w:type='page'/>` | `U+200B` x3 | `changed=True`, non-text intact |
| `carrier_mixed` | `carrier_mixed.docx` | Positive/Removal | Multi-part carriers in document body, table cell, header, and footer | `U+200B`, `U+00AD`, `U+2060`, `U+FEFF`, `U+200E` | `changed=True`, 3 parts modified |
| `carrier_and_legitimate_unicode` | `carrier_and_legitimate_unicode.docx` | Positive/Removal (Combined Gate) | Simultaneous presence of removable carriers AND legitimate counterexamples | Removable: `U+200B`, `U+00AD`, `U+200E`, `U+E0020`; Legitimate: `👨‍👩‍👧`, `می‌روم`, `क्‍ष`, `100 km` | Carriers removed; legitimate preserved byte-for-byte |
| `counterexample_emoji_zwj` | `counterexample_emoji_zwj.docx` | Counterexample-Only | Legitimate emoji sequences with ZWJ U+200D (family `👨‍👩‍👧`, technologist `👩‍💻`, astronaut `👨‍🚀`) | `U+200D` in emoji base context | `changed=False`, 0 FP, preserved |
| `counterexample_arabic_joiner` | `counterexample_arabic_joiner.docx` | Counterexample-Only | Legitimate Persian/Arabic ZWNJ (`می‌روم`) and ZWJ (`بـه`) in Arabic script | `U+200C`, `U+200D` in Arabic context | `changed=False`, 0 FP, preserved |
| `counterexample_devanagari` | `counterexample_devanagari.docx` | Counterexample-Only | Legitimate Devanagari shaping conjuncts (`क्‍ष`, `क्‌ष`) | `U+200D`, `U+200C` in Indic context | `changed=False`, 0 FP, preserved |
| `counterexample_nbsp` | `counterexample_nbsp.docx` | Counterexample-Only | Protected typographic spaces (U+00A0 NBSP, U+202F NNBSP) | `U+00A0`, `U+202F` | `changed=False`, 0 FP, preserved |
| `counterexample_nfc_nfd` | `counterexample_nfc_nfd.docx` | Counterexample-Only | Distinct NFC vs NFD Vietnamese diacritic encodings | NFC & NFD composite sequences | `changed=False`, 0 FP, distinct |

---

## 4. Evidence Classification & Invariant Verification

The Phase 6 micro-audit establishes evidence across five explicitly distinguished levels:

### 4.1 STRUCTURAL Evidence: Document Elements & Run Invariance
The frozen cleaner patches targeted text strictly within existing `<w:t>` tags via substring replacement in `DocxPatcher._patch_text_part`. It never deletes run elements (`<w:r>`), never merges adjacent runs, and never splits runs.
- **Run Count Invariance**: `run_count_before == run_count_after == 13` across all 12 fixtures.
- **Structural Invariance**:
  - Paragraph count: 8 $\rightarrow$ 8
  - Table count: 1 $\rightarrow$ 1
  - Table row count: 2 $\rightarrow$ 2
  - Table cell count: 4 $\rightarrow$ 4
  - Manual page break count: 1 $\rightarrow$ 1
  - Tab count: 1 $\rightarrow$ 1
  - Bookmark count: 1 $\rightarrow$ 1
  - Hyperlink count: 1 $\rightarrow$ 1
- **Non-Text Run Children**: In `carrier_with_non_text_children.docx`, paragraph 4 contains:
  `<w:r><w:t>Before</w:t><w:br/><w:t>Between</w:t><w:tab/><w:t>Tabbed</w:t><w:br w:type="page"/><w:t>After</w:t></w:r>`
  All carriers were removed while `<w:br/>`, `<w:tab/>`, and `<w:br w:type="page"/>` maintained their exact positions, tag attributes, and sibling order.
- **Status**: **PASS (100% Invariant)**

### 4.2 PACKAGE Evidence: Uncompressed Member Payload Hashes
For every fixture in the corpus, all uncompressed ZIP members outside `changed_parts` (such as `docProps/core.xml`, `docProps/app.xml`, `[Content_Types].xml`, `_rels/.rels`, `word/_rels/document.xml.rels`) retain 100% byte-identical SHA256 hashes before and after cleaning.
- **Status**: **PASS**

### 4.3 STRICT RAW OPC Evidence: Binary Pass-Through Identity
For representative positive fixtures (`carrier_zwsp.docx`, `carrier_mixed.docx`, `carrier_with_non_text_children.docx`, `carrier_and_legitimate_unicode.docx`), every non-target entry was independently audited against the binary ZIP archive. For every `NON_TARGET_UNCHANGED` member:
- A. Uncompressed payload SHA256: **IDENTICAL**
- B. Raw compressed payload bytes: **IDENTICAL**
- C. Compression method (`compress_type`): **IDENTICAL**
- D. CRC-32: **IDENTICAL**
- E. Compressed size: **IDENTICAL**
- F. Uncompressed size: **IDENTICAL**
- G. Flag bits: **IDENTICAL**
- H. External attributes: **IDENTICAL**
- I. Internal attributes: **IDENTICAL**
- J. Timestamp (`date_time`): **IDENTICAL**
- K. Extra field: **IDENTICAL**
- L. Comment: **IDENTICAL**
- M. Member ordering: **IDENTICAL**
- **Status**: **PASS (100% Invariant)**

#### Exact Changed Parts Accounting

| Representative Fixture | Planned Changed Parts | Actual Uncompressed Changed Parts | Actual Raw Changed Entries | Strict Raw Non-Target Status |
|---|---|---|---|---|
| `carrier_zwsp.docx` | `word/document.xml` | `word/document.xml` | `word/document.xml` | 7 non-target parts 100% raw-identical |
| `carrier_mixed.docx` | `word/document.xml`, `word/header1.xml`, `word/footer1.xml` | `word/document.xml`, `word/header1.xml`, `word/footer1.xml` | `word/document.xml`, `word/header1.xml`, `word/footer1.xml` | 5 non-target parts 100% raw-identical |
| `carrier_with_non_text_children.docx` | `word/document.xml` | `word/document.xml` | `word/document.xml` | 7 non-target parts 100% raw-identical |
| `carrier_and_legitimate_unicode.docx` | `word/document.xml` | `word/document.xml` | `word/document.xml` | 7 non-target parts 100% raw-identical |

### 4.4 RENDER Evidence: Headless LibreOffice Page Counts
Rendered via LibreOffice 26.8.0.3 (`C:\Program Files\LibreOffice\program\soffice.exe`) headless conversion:
- `synthetic_baseline.docx`: before = 2, after = 2 (**PASS**)
- `carrier_with_non_text_children.docx`: before = 2, after = 2 (**PASS**)
- `carrier_and_legitimate_unicode.docx`: before = 2, after = 2 (**PASS**)
- `counterexample_emoji_zwj.docx`: before = 2, after = 2 (**PASS**)
- `counterexample_arabic_joiner.docx`: before = 2, after = 2 (**PASS**)
- `counterexample_devanagari.docx`: before = 2, after = 2 (**PASS**)
- `counterexample_nbsp.docx`: before = 2, after = 2 (**PASS**)
- **Page Count Invariance**: 100% across all evaluated fixtures.

### 4.5 PIXEL Evidence: Corresponding Page Raster Comparison
Corresponding pages rendered to 2.0x scale RGB rasters:
- **Baseline & Counterexample-Only Fixtures**:
  - `synthetic_baseline.docx`: Page 1 identical=True, Page 2 identical=True
  - `counterexample_emoji_zwj.docx`: Page 1 identical=True, Page 2 identical=True
  - `counterexample_arabic_joiner.docx`: Page 1 identical=True, Page 2 identical=True
  - `counterexample_devanagari.docx`: Page 1 identical=True, Page 2 identical=True
  - `counterexample_nbsp.docx`: Page 1 identical=True, Page 2 identical=True
  - **Counterexample Pixel Identity**: **10/10 pages (100%) byte-for-byte pixel identical** (`diff_bbox=None`).
- **Positive Carrier Removal Fixtures**:
  - `carrier_and_legitimate_unicode.docx`:
    - Page 2 (table & trailing elements): **identical=True (`diff_bbox=None`)**
    - Page 1: dimensions identical `(1224, 1584)`; localized raster diff `(292, 150, 714, 225)` confined strictly to the heading and body paragraph lines where U+200B, U+00AD, U+200E, and U+E0020 were deleted.
  - `carrier_with_non_text_children.docx`:
    - Page 1 & Page 2: dimensions identical `(1224, 1584)`; localized raster diffs `(203, 231, 215, 247)` and `(233, 154, 243, 166)` confined strictly to character boundaries adjacent to removed ZWSPs.
  - **Analysis**: Font rasterization engines (HarfBuzz / FreeType inside LibreOffice) naturally recalculate micro-kerning and glyph advance widths when invisible control characters are removed. Page dimensions, line structures, and unmutated page areas remain identical.

---

## 5. Truthfulness & Product Scope Limitations

- **Declared Corpus False Positives**: **0** (no mutations detected on clean baseline or any counterexample fixture).
- **Supported Inserted Carriers False Negatives**: **0** (100% of inserted removable carriers were detected and planned).
- **Plan Parity**: For every fixture, `DocxMutationPlan.changed_parts()` matched the actual modified OOXML parts with zero phantom mutations.
- **Dry-Run Parity**: On `carrier_and_legitimate_unicode.docx`, `Pipeline.clean(dry_run=True)` produced `changed=False`, `would_change=True`, zero byte modifications, and identical mutation plans to real execution.
- **Idempotence**: A second clean pass over cleaned outputs returned `changed=False`, `mutations_count=0`, and `changed_parts=[]`.

### Critical Product Scope Limitation Note
The frozen DOCX carrier rules classify several bidirectional control characters (such as U+200E, U+200F, U+202A..U+202E, U+2066..U+2069) as unconditional `REMOVE` in SAFE mode.
- Phase 6 proves conformance to the current **frozen SAFE rule set**.
- Phase 6 does **NOT** establish that every possible real-world use of all bidirectional control characters in complex multilingual documents is semantically unnecessary.
- The claim of "0 false positives" is strictly scoped to the **declared Phase 6 counterexample corpus**.

---

## 6. Security, Privacy & Network Guarantees

- **Zero Network Invariant**: Socket monkeypatching verified zero TCP/UDP socket connections during inspection or cleaning of DOCX fixtures.
- **Report Privacy Invariant**: Inspection and cleaning reports were serialized and audited; no body text, run contents, or sensitive payload strings were leaked in report attributes or actions.

---

## 7. Canonical v2.0 Golden Regression

The v2.0 Golden regression tests were executed and passed without any regeneration:
- **Golden Original SHA256**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (VERIFIED)
- **Candidate Lossless Output SHA256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (VERIFIED)
- **Phase 5 Contract Regression**: 34 passed (`test_ui_contract.py`, `test_capabilities_endpoint.py`, `test_inspection_first.py`, `test_dry_run.py`).
