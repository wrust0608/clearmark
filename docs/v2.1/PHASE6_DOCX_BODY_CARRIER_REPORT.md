# ClearMark v2.1 — Phase 6 DOCX Body-Carrier & Contextual Preservation Report

**Phase Status**: **PASS**  
**Canonical Phase 5 Commit**: `ce07215b00234cf16f3c18e36ec570168ac57de5`  
**DOCX Frozen Core**: `service/scripts/docx/` (**UNMODIFIED — 0 DIFF AGAINST v2.0.0**)  
**Corpus Provenance**: `tests/fixtures/docx_body_carriers/build_fixtures.py`  
**Manifest**: `tests/fixtures/docx_body_carriers/MANIFEST.json`  
**Test Suite**: `tests/test_docx_body_carriers.py` (44 passed)  

---

## 1. Executive Summary

Phase 6 provides rigorous cryptographic, structural, and semantic evidence demonstrating that the existing frozen DOCX subsystem in `service/scripts/docx/`:
1. **Detects real invisible body carriers** within OOXML text nodes across paragraphs, multiple runs, table cells, headers, and footers.
2. **Plans only intended minimal mutations** without fabricated or phantom actions.
3. **Removes supported carriers in-place** inside existing `<w:t>` nodes without deleting runs or dropping non-text elements.
4. **Preserves legitimate contextual Unicode** (emoji ZWJ sequences, Arabic/Persian orthographic joiners, Devanagari shaping conjuncts, typographic non-breaking spaces, and NFC/NFD distinct encodings) with zero corruption.
5. **Preserves structural and layout invariants**:
   - `run_count_before == run_count_after` across all fixtures;
   - Invariant paragraph, table, row, cell, page-break, tab, bookmark, and hyperlink counts;
   - Non-text run children (`<w:br/>`, `<w:tab/>`, `<w:br w:type="page"/>`) remain in their exact sequence;
   - `xml:space="preserve"` attributes and whitespace boundaries remain intact.
6. **Preserves non-target OPC ZIP package members** byte-for-byte with identical SHA256 hashes.
7. **Maintains complete fidelity with zero network activity and zero report privacy leakage**.

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
- **Baseline Document**: `synthetic_baseline.docx` (SHA256: `94cffbfeac8dc590e82c5f11e9fbf3b3fa0fcf214bdfc08f657599026da68a73`)

### Fixture Inventory & Verification Matrix

| Fixture ID | Filename | Category | Purpose | Tested Codepoints | Result |
|---|---|---|---|---|---|
| `synthetic_baseline` | `synthetic_baseline.docx` | Baseline | Clean base document with multi-run paragraphs, table, header/footer, bookmark, hyperlink, and manual page break | None | `changed=False`, 0 mutations |
| `carrier_zwsp` | `carrier_zwsp.docx` | Positive Carrier | U+200B ZERO WIDTH SPACE carrier in body run and table cell | `U+200B` x3 | `changed=True`, 3 removed |
| `carrier_bidi_supported` | `carrier_bidi_supported.docx` | Positive Carrier | Supported directional bidi controls | `U+200E`, `U+200F`, `U+202A`, `U+202C`, `U+2066`, `U+2069` | `changed=True`, 6 removed |
| `carrier_unicode_tags` | `carrier_unicode_tags.docx` | Positive Carrier | Unicode Tag characters outside emoji flags | `U+E0001`, `U+E0020`, `U+E0041`, `U+E007F` | `changed=True`, 4 removed |
| `carrier_with_non_text_children` | `carrier_with_non_text_children.docx` | Positive Carrier | Carrier text adjacent to `<w:br/>`, `<w:tab/>`, and `<w:br w:type='page'/>` | `U+200B` x3 | `changed=True`, non-text intact |
| `carrier_mixed` | `carrier_mixed.docx` | Positive Carrier | Multi-part carriers in document body, table cell, header, and footer | `U+200B`, `U+00AD`, `U+2060`, `U+FEFF`, `U+200E` | `changed=True`, 3 parts modified |
| `counterexample_emoji_zwj` | `counterexample_emoji_zwj.docx` | Counterexample | Legitimate emoji sequences with ZWJ U+200D (family `👨‍👩‍👧`, technologist `👩‍💻`, astronaut `👨‍🚀`) | `U+200D` in emoji base context | `changed=False`, 0 FP, preserved |
| `counterexample_arabic_joiner` | `counterexample_arabic_joiner.docx` | Counterexample | Legitimate Persian/Arabic ZWNJ (`می‌روم`) and ZWJ (`بـه`) in Arabic script | `U+200C`, `U+200D` in Arabic context | `changed=False`, 0 FP, preserved |
| `counterexample_devanagari` | `counterexample_devanagari.docx` | Counterexample | Legitimate Devanagari shaping conjuncts (`क्‍ष`, `क्‌ष`) | `U+200D`, `U+200C` in Indic context | `changed=False`, 0 FP, preserved |
| `counterexample_nbsp` | `counterexample_nbsp.docx` | Counterexample | Protected typographic spaces (U+00A0 NBSP, U+202F NNBSP) | `U+00A0`, `U+202F` | `changed=False`, 0 FP, preserved |
| `counterexample_nfc_nfd` | `counterexample_nfc_nfd.docx` | Counterexample | Distinct NFC vs NFD Vietnamese diacritic encodings | NFC & NFD composite sequences | `changed=False`, 0 FP, distinct |
| `carrier_and_legitimate_unicode` | `carrier_and_legitimate_unicode.docx` | Combined Gate | Simultaneous presence of removable carriers AND legitimate counterexamples | Carriers: `U+200B`, `U+00AD`, `U+200E`, `U+E0020`; Legitimate: `👨‍👩‍👧`, `می‌روم`, `क्‍ष`, `100 km` | Carriers removed; legitimate preserved byte-for-byte |

---

## 4. Invariant Evidence & Verification

### 4.1 Run-Count Invariance (`run_count_before == run_count_after`)
The frozen cleaner patches targeted text strictly within existing `<w:t>` tags via substring replacement in `DocxPatcher._patch_text_part`. It never deletes run elements (`<w:r>`), never merges adjacent runs, and never splits runs. Across all 12 fixtures:
- `run_count_before`: 13
- `run_count_after`: 13
- **Status**: **PASS (100% Invariant)**

### 4.2 Structural Element Invariance
Across all positive carrier removals, every document structure metric remained strictly invariant:
- Paragraph count: 8 $\rightarrow$ 8
- Table count: 1 $\rightarrow$ 1
- Table row count: 2 $\rightarrow$ 2
- Table cell count: 4 $\rightarrow$ 4
- Manual page break count: 1 $\rightarrow$ 1
- Tab count: 1 $\rightarrow$ 1
- Bookmark count: 1 $\rightarrow$ 1
- Hyperlink count: 1 $\rightarrow$ 1
- **Status**: **PASS (100% Invariant)**

### 4.3 Non-Text Run Children Preservation
In `carrier_with_non_text_children.docx`, paragraph 4 contains:
`<w:r><w:t>Before</w:t><w:br/><w:t>Between</w:t><w:tab/><w:t>Tabbed</w:t><w:br w:type="page"/><w:t>After</w:t></w:r>`
All carriers were removed while `<w:br/>`, `<w:tab/>`, and `<w:br w:type="page"/>` maintained their exact positions, tag attributes, and sibling order.

### 4.4 Non-Target Member Cryptographic Payload Preservation
For every fixture, all uncompressed ZIP members outside `changed_parts` (such as `docProps/core.xml`, `docProps/app.xml`, `[Content_Types].xml`, `_rels/.rels`, `word/_rels/document.xml.rels`) were verified to have byte-identical SHA256 hashes before and after cleaning.

---

## 5. Truthfulness & Accuracy

- **Corpus False Positives**: **0** (no mutations detected on clean baseline or any counterexample fixture).
- **Corpus False Negatives**: **0** (100% of inserted removable carriers were detected and planned).
- **Plan Parity**: For every fixture, `DocxMutationPlan.changed_parts()` matched the actual modified OOXML parts with zero phantom mutations.
- **Dry-Run Parity**: On `carrier_and_legitimate_unicode.docx`, `Pipeline.clean(dry_run=True)` produced `changed=False`, `would_change=True`, zero byte modifications, and identical mutation plans to real execution.
- **Idempotence**: A second clean pass over cleaned outputs returned `changed=False`, `mutations_count=0`, and `changed_parts=[]`.

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
