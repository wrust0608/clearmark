# ClearMark v2.1 — Phase 8 PPTX Rule Matrix & Part Classification

**Status**: **APPROVED & CANONICAL**  
**Subsystem**: Lossless PresentationML / DrawingML (`service/scripts/pptx/`)  
**Processing Paradigm**: `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT`

---

## 1. Package Part Classification Matrix

Every part within a PowerPoint `.pptx` Open Packaging Conventions (OPC) container is mapped into one of five strict operational categories:

| Part Pattern | Category | Action in SAFE Mode | Rationale & Invariants |
|---|---|---|---|
| `ppt/slides/slide[0-9]+.xml` | `CLEAN_TEXT` | Surgical in-place text patch | User-facing slide body text within `<p:sp><p:txBody><a:p><a:r><a:t>` and `<p:graphicFrame><a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>`. Only planned target codepoints are mutated. Surrounding tags, `<a:rPr>`, and `<a:pPr>` are strictly preserved. |
| `docProps/core.xml` | `CLEAN_METADATA` | Empty tracking fields | Standard metadata scrubbing (`dc:creator`, `cp:lastModifiedBy`, `dc:description`). `dc:title` and structure remain intact. |
| `docProps/app.xml` | `CLEAN_METADATA` | Empty tracking fields | Standard extended metadata scrubbing (`Application`, `Company`). `AppVersion`, `TotalTime`, and slide counts remain intact. |
| `docProps/custom.xml` | `PRESERVE_RAW` | Byte-for-byte passthrough | Generic user-defined document properties must not be dropped without marker-specific high-confidence rules. |
| `customXml/*` | `PRESERVE_RAW` | Byte-for-byte passthrough | Arbitrary application custom XML is legitimate user data. Preserved raw with relationships and content types. |
| `ppt/presentation.xml` | `PRESERVE_RAW` | Byte-for-byte passthrough | Slide count, slide ordering (`<p:sldIdLst>`), master/layout references, and view properties are sacrosanct. |
| `ppt/slideMasters/*` | `PRESERVE_RAW` | Byte-for-byte passthrough | Template labels, layout defaults, and master shapes must not be treated as slide body text. |
| `ppt/slideLayouts/*` | `PRESERVE_RAW` | Byte-for-byte passthrough | Slide layout placeholders, geometry, and layout relationships must remain untouched. |
| `ppt/theme/*` | `PRESERVE_RAW` | Byte-for-byte passthrough | Color schemes, font schemes, format schemes, and theme XML remain bit-for-bit identical. |
| `ppt/notesSlides/*` | `NOT_CHECKED` | Byte-for-byte passthrough | Speaker notes are user-authored presentation data; out of scope for Phase 8 body cleaner. |
| `ppt/notesMasters/*` | `PRESERVE_RAW` | Byte-for-byte passthrough | Master definitions for speaker notes preserved verbatim. |
| `ppt/comments/*` | `NOT_CHECKED` | Byte-for-byte passthrough | Legacy and modern presentation comments are user conversations; not metadata to be deleted. |
| `ppt/commentAuthors.xml`| `PRESERVE_RAW` | Byte-for-byte passthrough | Comment author identity table preserved intact. |
| `ppt/media/*` | `PRESERVE_RAW` | Byte-for-byte passthrough | Embedded slide images/audio/video are presentation assets; image EXIF/XMP cleaning is an orthogonal workflow. |
| `ppt/charts/*` | `NOT_CHECKED` | Byte-for-byte passthrough | DrawingML chart definitions and chart workbooks preserved raw. |
| `ppt/diagrams/*` | `NOT_CHECKED` | Byte-for-byte passthrough | SmartArt and diagram data parts preserved raw. |
| `ppt/embeddings/*` | `NOT_CHECKED` | Byte-for-byte passthrough | OLE objects, embedded Excel/Word packages preserved verbatim without recursive descent. |
| `ppt/tags/*` | `PRESERVE_RAW` | Byte-for-byte passthrough | Presentation programmable tags preserved raw. |
| `ppt/viewProps.xml` | `PRESERVE_RAW` | Byte-for-byte passthrough | View scale, splitters, and view state preserved raw. |
| `ppt/tableStyles.xml` | `PRESERVE_RAW` | Byte-for-byte passthrough | Table styling definitions preserved raw. |
| `ppt/presProps.xml` | `PRESERVE_RAW` | Byte-for-byte passthrough | Presentation display properties preserved raw. |
| `_rels/.rels` | `PRESERVE_RAW` | Byte-for-byte passthrough | Top-level package relationships preserved intact. |
| `ppt/_rels/*.rels` | `PRESERVE_RAW` | Byte-for-byte passthrough | Presentation, slide, layout, and master relationships preserved verbatim. |
| `[Content_Types].xml` | `PRESERVE_RAW` | Byte-for-byte passthrough | MIME overrides and extension defaults preserved intact. |
| `vbaProject.bin` | `UNSUPPORTED` | FAIL_CLOSED | Macro-enabled presentations (`.pptm` / `.ppsm`) or embedded VBA code trigger fail-closed rollback. |
| `_xmlsignatures/*` | `UNSUPPORTED` | FAIL_CLOSED | Digitally signed packages trigger fail-closed rollback to prevent generating invalid signatures. |

---

## 2. DrawingML Invariant Guarantees

### 2.1 Shape Tree (`p:spTree`) Invariants
- Shape ordering within `<p:spTree>` is strictly preserved. Shapes are never re-ordered, appended, or detached.
- Shape identity attributes (`p:cNvPr/@id`, `p:cNvPr/@name`) are strictly invariant (no ID re-numbering or normalization).
- Shape types (`p:sp`, `p:pic`, `p:graphicFrame`, `p:grpSp`, `p:cxnSp`) remain identical.
- Placeholder attributes (`p:ph/@type`, `p:ph/@idx`) are preserved verbatim.

### 2.2 Geometry & Layout Invariants
- Visual properties (`p:spPr`) remain byte-for-byte identical.
- 2D Transform (`a:xfrm`) coordinates (`a:off/@x`, `a:off/@y`) and dimensions (`a:ext/@cx`, `a:ext/@cy`) are invariant.
- Rotation (`@rot`), flip flags (`@flipH`, `@flipV`), and geometry presets (`a:prstGeom/@prst`) remain untouched.

### 2.3 Paragraph & Run Invariants
- Paragraph count before == after (`len(paragraphs_before) == len(paragraphs_after)`).
- Ordered paragraph sequence and paragraph properties (`<a:pPr>`, `<a:endParaRPr>`) are preserved.
- Run count per paragraph before == after (`len(runs_before) == len(runs_after)`).
- Run properties (`<a:rPr>`) including font typeface, size (`sz`), bold (`b`), italic (`i`), color (`solidFill`), kerning, underline, and language (`lang`) are strictly invariant.
- Manual line breaks (`<a:br/>`) are preserved verbatim without conversion to runs or spaces.
- Field text (`<a:fld>`) nodes (such as slide numbers, dates, and footers) are treated as `NOT_CHECKED` / `PRESERVE_RAW` and are never mutated by normal run cleaners.
- Preserves `xml:space="preserve"` attributes across text nodes.

### 2.4 Tables (`a:tbl`) Invariants
- Grid configuration (`<a:tblGrid>`), column widths, row count, row heights (`<a:tr/@h>`), and cell merging (`rowSpan`, `gridSpan`) remain invariant.
- Cell properties (`<a:tcPr>`) including borders, margins, and background fills remain untouched.
- Only `<a:tc><a:txBody><a:p><a:r><a:t>` text payloads are eligible for planned cleaning.

### 2.5 Hyperlinks Invariants
- Text hyperlinks (`<a:rPr><a:hlinkClick r:id="..."/></a:rPr>`) and shape hyperlinks remain intact.
- Relationship IDs (`r:id`) pointing to external URLs or internal slide targets are preserved without alteration.

---

## 3. Strict Raw OPC Pass-Through Specification

For every non-target package member:
1. **Local File Header**: Verbatim copy of raw header bytes without reconstruction.
2. **Compressed Payload**: Verbatim copy of raw compressed byte stream without decompression/recompression.
3. **Compression Parameters**: Compression method (0 = Stored, 8 = Deflated), flags, timestamps, and CRC-32 checksum are 100% bit-for-bit identical.
4. **Central Directory Record**: All header metadata, filenames, and extra field flags are preserved byte-for-byte. Relative local header offsets accurately update if preceding modified target members change in size, ensuring valid ZIP structure without corruption. When preceding parts do not change size (or in empty-plan counterexamples), the central directory record is 100% byte-identical.
5. **Archive Member Order**: Exact order of entries in both the local stream and central directory is maintained.

---

## 4. Contextual Unicode & Counterexample Preservation

The detector applies strict contextual awareness to prevent false positives:
- **Emoji ZWJ Sequences**: Sequences containing `U+200D` (family, professions, gendered emoji) are strictly preserved (0 FP).
- **Arabic / Persian Orthographic Joiners**: `U+200C` (ZWNJ) and `U+200D` (ZWJ) in valid shaping contexts are preserved (0 FP).
- **Devanagari / Indic Conjuncts**: Virama conjunct sequences are preserved (0 FP).
- **Typographic Non-Breaking Spaces**: `U+00A0` (NBSP) and `U+202F` (NNBSP) are preserved (0 FP).
- **Unicode Normal Forms**: NFC and NFD encodings are preserved without canonical normalization.
- **Empty-Plan Zero-Copy**: Clean presentations with no detected carriers return the exact input bytes (`output_bytes is input_bytes`, SHA-256 identical, zero ZIP repackaging).
