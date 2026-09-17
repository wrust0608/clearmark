# ClearMark Format Capabilities & Runtime Policy Matrix

This document provides the authoritative, machine-checkable capability matrix for ClearMark (v2.1).
Every capability and constraint listed here is derived directly from the canonical runtime registry (`FormatPolicyRegistry` in `service/scripts/format_policy.py`) and is verifiable via the public CLI (`watermarks capabilities --json`) and the HTTP service (`GET /capabilities`).

---

## 1. Authoritative Format Capabilities Matrix

ClearMark registers **23 canonical policies** covering **37 file extensions** (23 canonical format names plus 14 extension aliases, representing 16 non-identity extension mappings).

| Canonical Policy | User Extensions | Inspection | Cleaning | Verify | Runtime State | Modes | Fidelity | Dependencies | Key Limitations |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| `audio` | `.mp3, .wav, .flac, .aac, .ogg, .m4a` | `tags, id3, xmp, c2pa, audio_watermark` | `tag_strip, c2pa_strip, audio_watermark_notch` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `ffmpeg` | In-process tag/metadata stripping; notch filtering requires balanced/aggressive modes. |
| `avif` | `.avif` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | Container metadata stripping; pixel inpainting bounded by raster limits. |
| `bmp` | `.bmp` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | Standard header metadata stripping; no deep container structures. |
| `docx` | `.docx` | `metadata, docProps, customXml, unicode_carriers, media_c2pa` | `docProps_scrub, customXml_drop, unicode_carrier_remove, media_meta_strip, raw_opc_preservation` | `structural_invariants, raw_opc_invariants, visible_text_exact` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D` | `NONE` | Frozen v2.0 OPC core; strict invariant validation; non-target parts byte-preserved. |
| `epub` | `.epub` | `metadata, manifest, text_runs` | `meta_scrub, manifest_prune, text_carrier_remove` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_B, LEVEL_C` | `NONE` | OPF metadata and manifest pruning; text-run carrier cleaning. |
| `gif` | `.gif` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | Comment extension and XMP chunk stripping; animation frame structures preserved. |
| `heic` | `.heic` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | ISOBMFF metadata box stripping; image item payloads preserved. |
| `html` | `.html, .htm` | `invisible_unicode, homoglyphs, stylometry, c2pa` | `invisible_unicode_remove, homoglyph_normalize, semantic_rewrite` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `NONE` | Zero-width Unicode and homoglyph normalization; DOM tree preserved. |
| `jpeg` | `.jpg, .jpeg` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | APP1/XMP/EXIF/IPTC marker segment stripping; DCT coefficients untouched in safe mode. |
| `latex` | `.tex, .latex` | `invisible_unicode, homoglyphs, stylometry, c2pa` | `invisible_unicode_remove, homoglyph_normalize, semantic_rewrite` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `NONE` | Invisible character stripping and Unicode normalization; macro syntax preserved. |
| `md` | `.md, .markdown` | `invisible_unicode, homoglyphs, stylometry, c2pa` | `invisible_unicode_remove, homoglyph_normalize, semantic_rewrite` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `NONE` | Invisible Unicode and zero-width character stripping; markdown structure preserved. |
| `odp` | `.odp` | `metadata, manifest, text_runs` | `meta_scrub, manifest_prune, text_carrier_remove` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_B, LEVEL_C` | `NONE` | ODF package metadata stripping; presentation shape tree preserved. |
| `ods` | `.ods` | `metadata, manifest, text_runs` | `meta_scrub, manifest_prune, text_carrier_remove` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_B, LEVEL_C` | `NONE` | ODF package metadata stripping; spreadsheet sheet/formula data preserved. |
| `odt` | `.odt` | `metadata, manifest, text_runs` | `meta_scrub, manifest_prune, text_carrier_remove` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_B, LEVEL_C` | `NONE` | ODF package metadata stripping; document text content preserved. |
| `pdf` | `.pdf` | `info_dict, xmp, c2pa, attachments, deep_images` | `info_scrub, xmp_strip, c2pa_strip, attachment_meta_clean, ghostscript_re-distill` | `NONE` | `DEPENDENCY_UNAVAILABLE` | `safe, balanced, aggressive` | `LEVEL_B, LEVEL_C` | `ghostscript, qpdf, c2patool` | Model B bounded fallback; deep image/attachment distillation requires optional tools. |
| `png` | `.png` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | Ancillary text/eXIf chunk stripping; verified structure required; IDAT untouched in safe mode. |
| `pptx` | `.pptx` | `metadata, docProps, slide_text, table_text` | `docProps_scrub, slide_carrier_remove, table_carrier_remove, raw_opc_preservation` | `structural_invariants, raw_opc_invariants, shape_tree_exact, geometry_exact, run_structure_exact` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D` | `NONE` | Shape tree, geometry, and layout preserved; slide/table carriers cleaned; raw OPC preservation. |
| `svg` | `.svg` | `metadata_tags, xml_comments, c2pa` | `meta_tags_drop, xml_comments_strip` | `NONE` | `AVAILABLE` | `safe` | `LEVEL_B, LEVEL_C` | `NONE` | Safe-mode only; metadata elements and XML comments dropped; path geometry preserved. |
| `tiff` | `.tif, .tiff` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | TIFF tag scrubbing; image strip/tile payloads preserved. |
| `txt` | `.txt` | `invisible_unicode, homoglyphs, stylometry, c2pa` | `invisible_unicode_remove, homoglyph_normalize, semantic_rewrite` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `NONE` | Unicode zero-width and homoglyph normalization; line break invariants preserved. |
| `video` | `.mp4, .mkv, .mov, .avi, .webm` | `tags, id3, xmp, c2pa, audio_watermark` | `tag_strip, c2pa_strip, audio_watermark_notch` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `ffmpeg` | In-process container tag/metadata stripping; track streams passed through. |
| `webp` | `.webp` | `EXIF, XMP, IPTC, C2PA, pixel_watermark` | `metadata, EXIF, XMP, metadata_strip, c2pa_strip, pixel_watermark_inpaint` | `NONE` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_C` | `c2patool, exiftool` | RIFF chunk stripping (EXIF, XMP); VP8/VP8L bitstream untouched in safe mode. |
| `xlsx` | `.xlsx` | `metadata, docProps, sharedStrings, inlineStrings` | `docProps_scrub, sharedStrings_carrier_remove, inlineStrings_carrier_remove, raw_opc_preservation` | `structural_invariants, raw_opc_invariants, formula_exact, style_invariants, shared_string_invariants` | `AVAILABLE` | `safe, balanced, aggressive` | `LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D` | `NONE` | Shared strings index stability; formulas and styles preserved; raw OPC preservation. |

---

## 2. Resource & Size Ceilings

Every ClearMark execution path enforces strict bounding constants to prevent out-of-memory errors, algorithmic complexity attacks, and decompression bombs. These limits are non-negotiable and strictly enforced before any mutation is attempted:

| Limit Context | Value | Enforcement Source | Behavior on Breach |
|:---|:---|:---|:---|
| **Top-Level File Input** | `256 MiB` (268,435,456 bytes) | `common.MAX_INPUT_BYTES` | Rejects file immediately; exit 6 / HTTP 413 |
| **CLI Stdin Stream** | `64 MiB` (67,108,864 bytes) | `common.MAX_STDIN_BYTES` | Aborts stdin ingest; exit 6 |
| **HTTP Input Payload** | `256 MiB` (268,435,456 bytes) | `server.MAX_INPUT_BYTES` | Rejects payload; HTTP 413 |
| **HTTP Request Body** | `384 MiB` (402,653,184 bytes) | `server.MAX_BODY_BYTES` | Rejects multipart/JSON body; HTTP 413 |
| **Batch Single-File Ceiling** | `32 MiB` (33,554,432 bytes) | `batch_processor.MAX_INPUT_BYTES` | Skips file with per-item `LIMIT_EXCEEDED` error |
| **Batch Aggregate Ceiling** | `200 MiB` (209,715,200 bytes) | `batch_processor.MAX_BATCH_TOTAL_BYTES` | Halts batch before processing; exit 6 / HTTP 413 |
| **Batch Item Count** | `100` files | `batch_processor.MAX_BATCH_FILES` | Halts batch before processing; exit 6 / HTTP 413 |
| **Batch Inline Output Delivery** | `32 MiB` (33,554,432 bytes) | `batch_processor.MAX_BATCH_INLINE_OUTPUT_BYTES` | Switches response mode to report-only; prevents server OOM |
| **ZIP Archive Member Count** | `10,000` entries | `security.SecurityLimits.max_member_count` | Rejects archive during preflight; exit 6 / HTTP 422 |
| **ZIP Member Uncompressed** | `64 MiB` (67,108,864 bytes) | `security.SecurityLimits.max_member_uncompressed_bytes` | Aborts archive member read; exit 6 / HTTP 422 |
| **ZIP Total Uncompressed** | `128 MiB` (134,217,728 bytes) | `security.SecurityLimits.max_total_uncompressed_bytes` | Aborts archive processing; exit 6 / HTTP 422 |
| **ZIP Compression Ratio** | `100x` (100.0:1) | `security.SecurityLimits.max_compression_ratio` | Rejects decompression bomb; exit 6 / HTTP 422 |
| **XML Part Byte Size** | `32 MiB` (33,554,432 bytes) | `security.SecurityLimits.max_xml_part_bytes` | Rejects oversized XML document part; exit 6 / HTTP 422 |
| **XML Total Byte Size** | `128 MiB` (134,217,728 bytes) | `security.SecurityLimits.max_total_xml_bytes` | Rejects oversized package XML; exit 6 / HTTP 422 |
| **XML Max Nesting Depth** | `100` levels | `security.SecurityLimits.max_xml_depth` | Rejects recursive XML entity structure; exit 6 / HTTP 422 |
| **XML Max Elements** | `500,000` elements | `security.SecurityLimits.max_xml_elements` | Rejects quadratic element expansion; exit 6 / HTTP 422 |

> [!NOTE]
> **Context Matters**: A 50 MiB file is permitted via single-file CLI (`watermarks clean input.docx`), but will be rejected if piped via stdin (64 MiB limit) or included in a batch operation (32 MiB per-file batch limit).

---

## 3. Exit Codes & Failure Contracts

ClearMark uses a consistent, machine-checkable exit code interface for single-file and batch CLI workflows:

| Code | Symbol | Canonical Category | Semantic Meaning |
|:---|:---|:---|:---|
| **0** | `SUCCESS` | Successful Clean / No Change | File was cleaned successfully, or inspection/dry-run finished with no changes required. |
| **2** | `UNSUPPORTED` | Unsupported Format | File format, extension, or container type is not supported by ClearMark. Exit 2 is strictly reserved for the UNSUPPORTED family; it is never used for limits or setup errors. |
| **3** | `VALIDATION_FAILED` | Invariant Verification Failure | Post-clean invariant checks detected an unauthoritative mutation; file was rolled back to original state. |
| **4** | `INVALID_INPUT` | Input Validation / Malformed | Input file is missing, empty, unreadable, zero inputs were matched, or command configuration was invalid. |
| **5** | `DEPENDENCY_MISSING` | Runtime Dependency Missing | A required external binary (e.g. ghostscript for deep PDF cleaning) is not installed on the system. |
| **6** | `LIMIT_EXCEEDED` | Processing Limit Exceeded | Input size, batch count, batch aggregate size, or archive structural limit exceeded configured bounds. |
| **7** | `BATCH_PARTIAL_FAILURE` | Additive Batch Result | Batch operation completed with mixed results (some files succeeded, while one or more failed). Also available via backward-compatible alias `BATCH_PARTIAL_SUCCESS`. |
| **10** | `INTERNAL_ERROR` | Internal Unhandled Failure | Unhandled exception or unexpected internal fault. |

---

## 4. HTTP API Status Mapping

The HTTP service maps canonical internal error codes (`ErrorCode` in `service/scripts/pipeline_types.py`) directly to standard HTTP status codes via `error_code_to_http_status()`:

| HTTP Status | Pipeline ErrorCode | Trigger Condition |
|:---|:---|:---|
| **200** | `OK` | Inspection, cleaning, verification, or capabilities request succeeded. |
| **400** | `INVALID_CONTAINER` | Archive container or file structure is corrupt, truncated, or syntactically invalid. |
| **413** | `PROCESSING_LIMIT_EXCEEDED` | Request body or payload exceeds byte ceilings (e.g. > 256 MiB payload, > 384 MiB body). |
| **415** | `UNSUPPORTED_FORMAT` | File format or extension is not registered in the canonical format policy registry. |
| **422** | `VALIDATION_FAILED`<br>`UNSUPPORTED_ARCHIVE_FEATURE` | Post-clean verification failed, or rejected archive features detected (e.g. ZIP64, ZipSlip, encrypted members). |
| **424** | `OPTIONAL_DEPENDENCY_MISSING` | Operation requires an external system dependency (e.g. ghostscript, qpdf) that is unavailable at runtime. |
| **500** | `INTERNAL_ERROR` | Internal processing error or unhandled server-side fault. |

---

## 5. Detection & Lifecycle Terminology

ClearMark strictly distinguishes between carrier detection states and pipeline outcomes to avoid misleading claims:

### Detection States (`DetectionStatus`)
- **`DETECTED`**: A supported provenance or watermark carrier was inspected and positively found.
- **`NOT_DETECTED`**: The specific checked surface was inspected, and no supported carrier was found.
- **`NOT_CHECKED`**: The surface was intentionally not inspected (e.g. to preserve complex layout invariants, or because no safe parser exists for that proprietary extension).
- **`UNAVAILABLE`**: The inspection engine for this surface requires an optional external dependency that is not present in the runtime environment.
- **`UNSUPPORTED`**: The format, sub-structure, or carrier type has no defined inspection policy.

> [!CAUTION]
> **`NOT_CHECKED` != `NOT_DETECTED`**: A surface marked `NOT_CHECKED` must never be interpreted as free of watermarks; it simply means ClearMark did not inspect that part of the file.

### Pipeline Outcomes (`PipelineStatus`)
- **`INSPECTED`**: Read-only inspection completed; findings reported.
- **`NO_CHANGE_REQUIRED`**: Supported surfaces were inspected and no authorized mutations were planned. This does **not** guarantee that every imaginable proprietary watermark is absent from the file.
- **`CLEANED`**: Authorized mutations were executed and all post-clean invariant checks passed.
- **`VALIDATION_FAILED`**: Post-clean invariant validation detected an anomaly; all mutations were rolled back. Original file is unaltered.
- **`UNSUPPORTED`**: Input format is not supported by ClearMark.
- **`ERROR`**: Processing halted due to an operational limit or system fault.

---

## 6. PDF Model-B Bounded Fallback

PDF files require special architectural handling because modern PDF structures can contain deeply embedded vector scripts, proprietary font encodings, and raster watermarks:

1. **Standard In-Process Fallback**: ClearMark includes a bounded standard-library fallback cleaner capable of inspecting standard Document Information dictionaries (`/Info`) and stripping top-level Extensible Metadata Platform (`XMP`) streams without external dependencies.
2. **Deep Cleaning Surfaces**: Removing deep raster image watermarks, embedded file attachments, and executing structural re-distillation requires optional external tools: `ghostscript`, `qpdf`, and `c2patool`.
3. **Fail-Closed Missing Dependency Protocol**: If an inspected PDF contains carriers that require deep cleaning and the required external dependency is missing, ClearMark returns **`OPTIONAL_DEPENDENCY_MISSING`** (exit code 5, HTTP 424). It **never** silently maps this condition to `NO_CHANGE_REQUIRED`.
