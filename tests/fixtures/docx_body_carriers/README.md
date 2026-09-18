# ClearMark v2.2 — DOCX Body-Carrier & Counterexample Fixture Corpus

**Corpus Version**: 2.2.0  
**Baseline Document**: `synthetic_baseline.docx` (SHA256: `fad4c7d909ccb7a49f1d0a397a652a3c976e53b1685cb19651ca4d8eb55d987d`)  
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
