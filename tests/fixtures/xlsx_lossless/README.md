# Phase 7 XLSX Lossless Fixture Corpus

Deterministic synthetic test fixtures for the ClearMark v2.1 XLSX Lossless Adapter.

## Provenance
- Generator: `build_fixtures.py`
- Fixed Archive Timestamp: `2026-01-01 00:00:00`
- Compression: `ZIP_DEFLATED` level 9
- Total Fixtures: `12`

## Fixture Inventory

| Fixture ID | Filename | Category | Description | Tested Codepoints | Expected Mutations |
|---|---|---|---|---|---|
| `synthetic_baseline` | `synthetic_baseline.xlsx` | `baseline` | Clean 2-sheet workbook with shared strings, inline string, rich text, formula, styles, merged range, and hyperlink | `None` | `0` |
| `carrier_shared_string` | `carrier_shared_string.xlsx` | `positive_carrier` | U+200B carrier embedded inside xl/sharedStrings.xml <si><t> | `U+200B` | `1` |
| `carrier_inline_string` | `carrier_inline_string.xlsx` | `positive_carrier` | U+200C carrier embedded inside sheet1.xml inline string <is><t> | `U+200C` | `1` |
| `carrier_rich_text` | `carrier_rich_text.xlsx` | `positive_carrier` | U+200D carrier embedded inside rich text run <si><r><t> | `U+200D` | `1` |
| `carrier_cross_reference` | `carrier_cross_reference.xlsx` | `positive_carrier` | Multiple cells (A1, B1, C1) reference the same shared string index containing U+200B | `U+200B` | `1` |
| `carrier_mixed` | `carrier_mixed.xlsx` | `positive_carrier` | Carriers across shared strings, inline string, rich text, core.xml, app.xml, customXml, and custom.xml | `U+200B, U+E0001` | `7` |
| `carrier_and_legitimate_unicode` | `carrier_and_legitimate_unicode.xlsx` | `positive_carrier` | Carrier U+200B alongside legitimate emoji ZWJ, Persian ZWNJ, Devanagari conjuncts, and NBSP | `U+200B` | `1` |
| `counterexample_emoji_zwj` | `counterexample_emoji_zwj.xlsx` | `counterexample` | Legitimate emoji ZWJ sequence (U+200D in 👨‍👩‍👧‍👦); expected zero mutations | `U+200D (in emoji sequence)` | `0` |
| `counterexample_arabic_joiner` | `counterexample_arabic_joiner.xlsx` | `counterexample` | Legitimate Persian orthographic ZWNJ (U+200C in می‌روم); expected zero mutations | `U+200C (in Persian text)` | `0` |
| `counterexample_devanagari` | `counterexample_devanagari.xlsx` | `counterexample` | Legitimate Devanagari halant conjunct (U+200D in क्‍ष); expected zero mutations | `U+200D (in Devanagari text)` | `0` |
| `counterexample_nbsp` | `counterexample_nbsp.xlsx` | `counterexample` | Typographic spaces (U+00A0 NBSP and U+202F NNBSP); expected zero mutations in SAFE mode | `U+00A0, U+202F` | `0` |
| `counterexample_nfc_nfd` | `counterexample_nfc_nfd.xlsx` | `counterexample` | Distinct NFC (U+00E9) and NFD (U+0065 U+0301) encodings preserved without forced normalization | `U+00E9, U+0301` | `0` |
