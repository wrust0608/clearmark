# ClearMark Format Guarantees & Fidelity Specifications

This document defines the exact structural, semantic, and invariant preservation guarantees provided by ClearMark (v2.1). All guarantees documented here are grounded in executable regression suites and validated test fixtures.

---

## 1. Guarantee Levels (`FidelityLevel`)

ClearMark categorizes format preservation guarantees into four explicit, verifiable levels defined in `service/scripts/format_policy.py`:

- **`LEVEL_A` — Byte-Preserving Non-Target Parts**: Raw ZIP/OPC pass-through preserves untouched package members byte-for-byte. Original compression methods, deflated bitstreams, local file headers, and CRC32 checksums are unmodified for non-target parts.
- **`LEVEL_B` — Structural Invariant Preservation**: Complete preservation of document and container structural trees (e.g. XML DOM hierarchy, shape trees, cell coordinate matrices, presentation layouts, and table topologies).
- **`LEVEL_C` — Semantic & Visible Text Content Invariants**: Canonical visible text content, reading order, word boundaries, and linguistic semantics are strictly preserved across cleaning operations.
- **`LEVEL_D` — Visual Rendering Regression Safety**: Cleaned documents render identically to original documents across tested viewing engines, verified by visual rasterization checks and page layout audits.

---

## 2. Universal Pipeline Guarantees

The following foundational guarantees apply unconditionally across all supported formats:

1. **Inspection-First Workflow**:
   - `watermarks inspect` is strictly read-only. It reads inputs into memory, scans for known carrier patterns, and emits diagnostic findings without modifying files on disk.
   - `watermarks clean --dry-run` performs mutation planning and validation in-memory, reporting planned changes (`would_change`) with zero disk mutation.
2. **Security Preflight & Reject-Before-Mutation**:
   - All structured containers and archives are validated against hostile attack patterns before any mutation is attempted.
   - Archives containing directory traversal paths (ZipSlip), recursive decompression bombs (ZipBomb exceeding 100x ratio or 128 MiB uncompressed size), or XML entity expansions (XXE / Billion Laughs) are rejected immediately in preflight.
   - ClearMark enforces a strict **fail-closed** policy for ZIP64 extensions to avoid format ambiguities.
3. **Report Privacy & Zero Data Egress**:
   - Canonical ClearMark execution is 100% local and produces zero network egress.
   - Diagnostic reports (`CleaningReport`) record metadata carrier names, detection states, and performance metrics. Document body text is intentionally excluded from reports.
4. **Idempotence ($C(C(x)) == C(x)$)**:
   - For all runtime-available format policies, cleaning an already-cleaned file a second time with the same mode and options produces identical byte content.
5. **Fail-Closed Validation**:
   - Every mutation pipeline is followed by post-clean invariant validation. If any declared invariant check fails, mutations are rolled back and the original file is preserved unaltered.

---

## 3. Microsoft Office OOXML Guarantees (DOCX, XLSX, PPTX)

DOCX, XLSX, and PPTX formats are governed by dedicated structural engines designed to eliminate destructive parse-and-rebuild side effects.

### DOCX Guarantees (Frozen v2.0 Core)
The DOCX subsystem uses the frozen v2.0 engine located in `service/scripts/docx/`:
- **Minimal Targeted Patching**: Uses an explicit `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT` pipeline. XML parts that contain no watermarks are left completely untouched.
- **Raw OPC Pass-Through**: Non-target parts (styles, fonts, theme definitions, media items, embedded objects) are copied byte-for-byte from the input archive without decompression or re-serialization.
- **Run & Boundary Preservation**: Run-level carrier detection injects `xml:space="preserve"` where needed to prevent adjacent run concatenation or word-gluing (e.g. preserving compound words across runs).
- **Structural Invariants**: Paragraph IDs, comment anchors, bookmarks, math elements (`m:oMath`), drawing shapes, and revision tracking markers are preserved.
- **Post-Clean Verification**: Automated 4-layer verification verifies package integrity, raw OPC hash equality on non-target members, and visible text equality.

### XLSX Guarantees
- **Shared String Stability**: Shared strings are updated in place within their existing `<si>` elements without re-indexing or deduplication. Shared-string indices and referring cell indices (`<c t="s"><v>N</v></c>`) remain unchanged.
- **Formula & Calculation Safety**: Formula strings, calculation chains, array formulas, and cell coordinate grids are strictly preserved.
- **Styles & Formatting Fidelity**: Number formats, fonts, fills, borders, cell styles, and conditional formatting rules remain byte-stable or structurally invariant.
- **Raw OPC Pass-Through**: Untouched sheets, drawing definitions, and binary workbook parts are copied directly via raw byte pass-through.

### PPTX Guarantees
- **Shape Tree & Geometry Integrity**: Shape identifiers, z-ordering, 2D transform offsets, grouping hierarchies, and geometry definitions are strictly preserved.
- **Layout & Master Preservation**: Slide masters, slide layouts, themes, notes, and presentation properties are preserved.
- **Table Topologies**: Table grids, row heights, column widths, and cell merging structures are preserved during text cleaning.
- **Explicit `NOT_CHECKED` Boundaries**: Complex animation paths, embedded audio/video streams, and VBA macro storage streams are intentionally not altered and preserved as `NOT_CHECKED`.

---

## 4. Generic Containers (ODT, ODS, ODP, EPUB, SVG)

Generic containers do not use the OOXML raw OPC pass-through engine. Their guarantees reflect their specific container architectures:

- **OpenDocument Formats (ODT, ODS, ODP)**: ClearMark scrubs metadata from `meta.xml` and targeted text-run carriers from `content.xml`. Manifests, styles (`styles.xml`), and embedded graphics are preserved.
- **EPUB eBooks**: Metadata entries in the Open Packaging Format (`.opf`) file and metadata tags in HTML content documents are cleaned. Navigational tables of contents, manifest IDs, and spine hierarchies are preserved.
- **SVG Vector Graphics**: Supported strictly in **`safe` mode**. Metadata tags (`<metadata>`, `<rdf:RDF>`) and XML comments are pruned. Vector paths (`<path>`, `<rect>`, `<circle>`), coordinate systems, CSS styling, and viewBox transformations are preserved.

---

## 5. Text & Unicode Formats (TXT, MD, HTML, LaTeX)

Text cleaners target covert algorithmic watermarks embedded in character streams:
- **Carrier Classification & Contextual Preservation**: Scans and strips covert invisible-character watermark sequences (such as isolated zero-width spaces `U+200B`, left-to-right/right-to-left marks `U+200E`/`U+200F`, and tag characters `U+E0001`–`U+E007F`). Legitimate contextual joiners are strictly preserved: emoji ZWJ sequences (e.g. `U+200D` between emoji bases for family and professional glyphs) and orthographic script joiners (`U+200C` ZWNJ and `U+200D` ZWJ in Arabic, Persian, and Devanagari conjuncts) are identified and kept intact. `U+200C` and `U+200D` are never unconditionally stripped; only unattached, isolated, or covert carrier occurrences are pruned.
- **Homoglyph Normalization**: Normalizes lookalike Cyrillic, Greek, or mathematical symbols back to standard Latin characters according to Unicode equivalence tables.
- **Line Break & Encoding Invariants**: File line endings (CRLF vs LF) and character encodings (UTF-8) are strictly preserved.
- **Markup Protection**: For Markdown, HTML, and LaTeX, syntax characters (tags, code fences, inline formulas, and command macros) are preserved.

---

## 6. Image Formats (PNG, JPEG, WebP, GIF, BMP, TIFF, AVIF, HEIC)

Image format policies govern metadata and structural provenance carriers:
- **Verified Carrier Requirement**: Provenance removal requires a validated, supported structural carrier (e.g. standard chunk, EXIF directory, or XMP packet). ClearMark **never** drops arbitrary private image chunks simply because unparsed raw byte payloads match a substring search.
- **Safe-Mode Metadata Stripping**: In `safe` mode, ClearMark prunes ancillary metadata segments (EXIF, IPTC, XMP, comments, C2PA JUMBF chunks) without re-encoding compressed image pixels (IDAT for PNG, DCT for JPEG, VP8 for WebP).
- **Pixel Inpainting Scoping**: Raster watermark inpainting (under `balanced` or `aggressive` mode) alters pixel values within targeted bounding regions. Pixel values are therefore **not** claimed to be byte-identical or lossless when pixel inpainting is explicitly requested.

---

## 7. C2PA Provenance Scoping

ClearMark clearly differentiates between structural metadata carriers and cryptographic claims:
- **Supported Action**: ClearMark detects and strips structural C2PA manifests and JUMBF boxes (e.g. in PNG `c2pa` chunks, JPEG APP11 segments, MP4 `uuid` boxes, or PDF catalog dictionaries).
- **Non-Guarantee**: ClearMark does **not** cryptographically validate digital signature chains, certificate authorities, or hardware roots of trust for C2PA manifests. Stripping a C2PA carrier removes the provenance manifest; it does not constitute a cryptographic proof of content authenticity.

---

## 8. Audio & Video Formats (WAV, MP3, FLAC, MP4, MKV, etc.)

- **Canonical In-Process Cleaning**: Canonical cleaning for audio (WAV, MP3, FLAC) and video (MP4) containers operates **100% in-process** via Python standard library byte parsers across all supported modes (`safe`, `balanced`, `aggressive`). Canonical pipeline cleaning spawns **zero subprocesses** and does **not** require or invoke `ffmpeg`.
- **Audio/Video Stream Invariance**: Elementary audio (PCM, AAC, MP3) and video (H.264, HEVC) bitstreams are passed through unchanged in `safe` mode without re-encoding.
- **Standalone Purifiers vs Canonical Pipeline**: External utilities (`ffmpeg`) are utilized solely for standalone destructive purifiers (e.g. `audio_purify` invoked via service endpoint option `remove_audio_watermark`), which apply acoustic transformations. The canonical pipeline clean path does not invoke these external tools.

---

## 9. PDF Model-B Bounded Fallback

PDF files are handled via a two-tier execution model:
1. **Standard In-Process Fallback**: ClearMark's standard-library engine inspects and sanitizes top-level trailer dictionaries (`/Info`), document metadata streams, and standard `/XMP` packets.
2. **Deep Cleaning Surfaces**: Complex operations—such as stripping raster image watermarks embedded inside content streams, cleaning deep attachments, or executing structural re-distillation—require external tools (`ghostscript`, `qpdf`, `c2patool`).
3. **Explicit Failure Contract**: If deep cleaning is required but the corresponding dependency is missing, ClearMark halts and returns **`OPTIONAL_DEPENDENCY_MISSING`** (exit 5 / HTTP 424). It does not silently pretend the uncleaned file requires no changes.

---

## 10. Understanding Status & Limitations

### `NOT_CHECKED` Semantics
Surfaces marked as `NOT_CHECKED` indicate areas deliberately omitted from inspection to preserve high-risk structural components. Never assume an omitted surface is clean.

### `NO_CHANGE_REQUIRED` Semantics
When ClearMark reports `NO_CHANGE_REQUIRED`, it guarantees only that **all supported, configured surfaces for that format policy were inspected and contained no recognizable provenance carriers**. It does not guarantee that no proprietary, encrypted, or novel semantic watermarking scheme exists within the file.

---

## 11. Two-File Verification Engine (`watermarks verify`)

ClearMark provides an executable verification engine for supported formats (`docx`, `xlsx`, `pptx`):

```bash
# PowerShell / Bash
watermarks verify original.docx candidate.docx --json
```

The verification engine performs a two-stage evaluation:
1. **Security Preflight**: Ensures candidate file conforms to container safety bounds.
2. **Fidelity Audit**: Verifies that non-target OPC parts remain identical, structural trees conform to expected schemas, and visible text content matches the original source exactly.
