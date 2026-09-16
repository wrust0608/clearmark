# ClearMark v2.1 — Phase 6 DOCX Body-Carrier Rule Matrix

**Status**: AUDITED & GROUNDED IN FROZEN DOCX SUBSYSTEM  
**Core Implementation**: `service/scripts/docx/detector.py`, `service/scripts/docx/patcher.py`, `service/scripts/docx/validator.py`  
**Referenced Module**: `service/scripts/text_unicode.py`  
**Default Mode Under Test**: `ProcessingMode.SAFE` (`also_layer_a_text=True`, `normalize_spaces=False`)

---

## 1. Classification Categories

- **REMOVE**: Unconditionally detected as an ungrounded carrier in SAFE mode and stripped by `DocxPatcher`.
- **PRESERVE_CONTEXTUALLY**: Preserved when occurring in valid linguistic or presentation contexts (emoji sequences, complex scripts, CJK ideographs); stripped as a carrier only when free-floating or outside those valid contexts.
- **NOT_SUPPORTED**: Not recognized as a removable carrier or actionable construct by the frozen DOCX detector.
- **NOT_CHECKED**: Location or construct outside the operational scope of the frozen DOCX subsystem (e.g. `word/comments.xml`).

---

## 2. Comprehensive Codepoint & Range Classification

| Codepoint / Range | Character / Sequence Name | Frozen DOCX Classification | Rule / Context Condition |
|---|---|---|---|
| **U+200B** | ZERO WIDTH SPACE | **REMOVE** | Member of `SAFE_CARRIERS`. Removed from all `<w:t>` in supported body parts. |
| **U+00AD** | SOFT HYPHEN | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+034F** | COMBINING GRAPHEME JOINER | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+115F** | HANGUL CHOSEONG FILLER | **REMOVE** | Member of `SAFE_CARRIERS` in DOCX subsystem. |
| **U+1160** | HANGUL JUNGSEONG FILLER | **REMOVE** | Member of `SAFE_CARRIERS` in DOCX subsystem. |
| **U+17B4** | KHMER VOWEL INHERENT AQ | **REMOVE** | Member of `SAFE_CARRIERS` in DOCX subsystem. |
| **U+17B5** | KHMER VOWEL INHERENT AA | **REMOVE** | Member of `SAFE_CARRIERS` in DOCX subsystem. |
| **U+180B..U+180D** | MONGOLIAN FREE VARIATION SELECTOR 1..3 | **REMOVE** | Member of `SAFE_CARRIERS` in DOCX subsystem. |
| **U+180E** | MONGOLIAN VOWEL SEPARATOR | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+180F** | MONGOLIAN FREE VARIATION SELECTOR 4 | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+200E** | LEFT-TO-RIGHT MARK (LRM) | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+200F** | RIGHT-TO-LEFT MARK (RLM) | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+202A..U+202E** | BIDI CONTROLS (LRE, RLE, PDF, LRO, RLO) | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+2060** | WORD JOINER (WJ) | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+2061..U+2064** | INVISIBLE OPERATORS (TIMES, SEPARATOR, PLUS) | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+2066..U+2069** | BIDI ISOLATES (LRI, RLI, FSI, PDI) | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+3164** | HANGUL FILLER | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+FEFF** | ZERO WIDTH NO-BREAK SPACE / BOM | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+FFA0** | HALFWIDTH HANGUL FILLER | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+FFF9..U+FFFB** | INTERLINEAR ANNOTATION (ANCHOR, SEP, TERM) | **REMOVE** | Member of `SAFE_CARRIERS`. |
| **U+E0001..U+E007F** | UNICODE TAG CHARACTERS | **REMOVE** | Explicit range check `0xE0001 <= cp <= 0xE007F`. |
| **U+FDD0..U+FDEF** | UNICODE NONCHARACTERS (BMP) | **REMOVE** | Explicit range check `0xFDD0 <= cp <= 0xFDEF`. |
| **U+nFFFE..U+nFFFF** | NONCHARACTERS (Plane Terminals) | **REMOVE** | `(cp & 0xFFFE) == 0xFFFE`. |
| **U+2065, U+E0000** | RESERVED DEFAULT IGNORABLE | **REMOVE** | Explicit codepoint checks. |
| **U+FFF0..U+FFF8** | RESERVED SPECIALS | **REMOVE** | Explicit range check `0xFFF0 <= cp <= 0xFFF8`. |
| **U+200D (Emoji)** | ZERO WIDTH JOINER in Emoji | **PRESERVE_CONTEXTUALLY** | Preserved if surrounded by emoji bases (`_is_emoji_base(prev_cp)` and `_is_emoji_base(next_cp)`). Otherwise removed. |
| **U+200C, U+200D (Arabic)** | ZWNJ / ZWJ in Arabic | **PRESERVE_CONTEXTUALLY** | Preserved if flanked by Arabic letters (`0x0600 <= cp <= 0x08FF`). Otherwise removed. |
| **U+200C, U+200D (Indic)** | ZWNJ / ZWJ in Devanagari / Indic | **PRESERVE_CONTEXTUALLY** | Preserved if flanked by Indic letters (`0x0900 <= cp <= 0x0DFF`). Otherwise removed. |
| **U+200C, U+200D (Khmer)** | ZWNJ / ZWJ in Khmer | **PRESERVE_CONTEXTUALLY** | Preserved if flanked by Khmer letters (`0x1780 <= cp <= 0x17FF`). Otherwise removed. |
| **U+FE0E, U+FE0F** | VARIATION SELECTOR 15..16 | **PRESERVE_CONTEXTUALLY** | Preserved after emoji bases (`_is_emoji_base(prev_cp)`). Otherwise removed. |
| **U+FE00..U+FE0F, U+E0100..U+E01EF** | VARIATION SELECTORS in CJK | **PRESERVE_CONTEXTUALLY** | Preserved after CJK unified ideographs (`0x4E00..0x9FFF`, `0x3400..0x4DBF`). Otherwise removed. |
| **U+00A0** | NO-BREAK SPACE (NBSP) | **NOT_SUPPORTED** (Preserved in SAFE) | In SAFE mode (`normalize_spaces=False`), `SPACE_HOMOGLYPHS` are NOT considered safe carriers and remain untouched. |
| **U+2000..U+200A** | EN/EM/THIN/HAIR SPACES | **NOT_SUPPORTED** (Preserved in SAFE) | Preserved byte-for-byte in SAFE mode. |
| **U+202F** | NARROW NO-BREAK SPACE | **NOT_SUPPORTED** (Preserved in SAFE) | Preserved byte-for-byte in SAFE mode. |
| **U+3000** | IDEOGRAPHIC SPACE | **NOT_SUPPORTED** (Preserved in SAFE) | Preserved byte-for-byte in SAFE mode. |
| **U+061C** | ARABIC LETTER MARK (ALM) | **NOT_SUPPORTED** | Not present in `docx/detector.py` `SAFE_CARRIERS`. Untouched in DOCX. |
| **U+0410..U+044F** | CYRILLIC CONFUSABLES | **NOT_SUPPORTED** | Confusable Latin lookalikes are not in SAFE DOCX carrier rules. |
| **U+E000..U+F8FF** | PRIVATE USE AREA (PUA) | **NOT_SUPPORTED** | Not present in `docx/detector.py` `SAFE_CARRIERS`. Untouched in DOCX. |

---

## 3. Supported Body Location Scope

| OOXML Package Part | Frozen Detector Scope | Status |
|---|---|---|
| `word/document.xml` | Scanned (`w:p -> w:r -> w:t`) | **SUPPORTED** |
| `word/header1.xml..headerN.xml` | Scanned (`w:p -> w:r -> w:t`) | **SUPPORTED** |
| `word/footer1.xml..footerN.xml` | Scanned (`w:p -> w:r -> w:t`) | **SUPPORTED** |
| `word/footnotes.xml` | Scanned (`w:p -> w:r -> w:t`) | **SUPPORTED** |
| `word/endnotes.xml` | Scanned (`w:p -> w:r -> w:t`) | **SUPPORTED** |
| Paragraph text (`w:p/w:r/w:t`) | Scanned | **SUPPORTED** |
| Table text (`w:tbl/w:tr/w:tc/w:p/w:r/w:t`) | Scanned (via `iter('{...}p')`) | **SUPPORTED** |
| `word/comments.xml` | Not in regex `word/(?:document\|header\d+\|footer\d+\|footnotes\|endnotes)\.xml` | **NOT_CHECKED / OUT_OF_SCOPE** |
| `word/settings.xml` | Not scanned for body text | **NOT_CHECKED / OUT_OF_SCOPE** |
| `word/fontTable.xml` | Not scanned for body text | **NOT_CHECKED / OUT_OF_SCOPE** |

---

## 4. Run Preservation & Structural Invariant Rules

1. **Run Invariance**:
   `DocxPatcher._patch_text_part` iterates over text nodes (`<w:t>...</w:t>`) and replaces characters within the node text payload.
   It NEVER deletes `<w:r>`, creates `<w:r>`, or splits `<w:r>`.
   `run_count_before == run_count_after` is guaranteed structurally.
2. **Non-Text Run Children**:
   Child elements of `<w:r>` such as `<w:rPr>`, `<w:br/>`, `<w:br w:type="page"/>`, and `<w:tab/>` exist outside `<w:t>...</w:t>`.
   The patcher operates strictly on `<w:t>` slice boundaries and does not modify sibling run elements.
3. **`xml:space="preserve"` Attribute**:
   If a patched text string starts or ends with whitespace and `xml:space="preserve"` was absent on `<w:t>`, `DocxPatcher` explicitly adds `xml:space="preserve"` to prevent Word parser trimming. Existing `xml:space="preserve"` is preserved.
4. **NFC/NFD Integrity**:
   No Unicode canonical decomposition or composition is performed during patching. Non-carrier characters are emitted in their exact original codepoints.
