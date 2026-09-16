# Phase 8 PPTX Lossless Fixtures Corpus

Deterministic test corpus for ClearMark v2.1 PPTX Lossless Adapter.

## Generation
Generated deterministically by `build_fixtures.py` with fixed ZIP timestamps (`2026-01-01 00:00:00`) and standard ZIP deflate compression.

## Corpus Summary
- **Total Fixtures**: 17
- **Baseline**: 1 (`synthetic_clean_baseline.pptx`)
- **Positive Carrier Fixtures**: 5
  - `carrier_slide_text.pptx`: Zero-width space in slide shape run.
  - `carrier_multi_run.pptx`: Carriers across multiple runs in a slide paragraph.
  - `carrier_table_text.pptx`: Carrier inside table cell `<a:tc>` run.
  - `carrier_mixed.pptx`: Slide text, table text, and standard docProps metadata.
  - `carrier_and_legitimate_unicode.pptx`: Zero-width carrier alongside legitimate emoji ZWJ sequence.
- **Counterexample Fixtures**: 11
  - `counterexample_emoji_zwj.pptx`: Legitimate emoji ZWJ sequence preserved.
  - `counterexample_arabic_joiner.pptx`: Legitimate Persian/Arabic ZWNJ/ZWJ preserved.
  - `counterexample_devanagari.pptx`: Legitimate Devanagari virama/joiners preserved.
  - `counterexample_nbsp.pptx`: Legitimate NBSP / NNBSP preserved.
  - `counterexample_nfc_nfd.pptx`: Combining diacritical accents preserved.
  - `counterexample_custom_properties.pptx`: `docProps/custom.xml` preserved raw in SAFE mode.
  - `counterexample_custom_xml.pptx`: `customXml/item1.xml` preserved raw in SAFE mode.
  - `counterexample_field.pptx`: `<a:fld>` text preserved raw (NOT_CHECKED).
  - `counterexample_notes.pptx`: Speaker notes slide text preserved raw (NOT_CHECKED).
  - `counterexample_master.pptx`: Slide master text preserved raw (NOT_CHECKED).
  - `counterexample_group_shape.pptx`: Grouped shape text preserved raw (NOT_CHECKED).

## Invariants
All fixtures adhere to machine-readable expectations in `MANIFEST.json`.
