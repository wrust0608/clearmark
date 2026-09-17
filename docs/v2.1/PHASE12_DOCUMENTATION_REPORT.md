# Phase 12 Documentation & Capabilities Truthfulness Report

**Date**: 2026-09-17  
**Branch**: `v2.1-dev`  
**Phase Status**: **PASS / COMPLETED**  
**Phase 13 Status**: **NOT STARTED**  

---

## 1. Executive Summary

Phase 12 establishes truthful, machine-checkable, and executable user-facing documentation for ClearMark (v2.1).
All capability claims, format guarantees, size and resource limits, exit codes, and HTTP endpoint behaviors in public documentation are derived directly from executable runtime truth (`FormatPolicyRegistry` in `service/scripts/format_policy.py`, `service/scripts/server.py`, `service/scripts/cli.py`, and production limit constants).

A dedicated consistency test suite (`tests/test_docs_capabilities_consistency.py`) has been added as an automated gate, preventing documentation staleness, capability inflation, broken links, or privacy leaks in all future commits.

---

## 2. Canonical Source-of-Truth Model

ClearMark's documentation architecture strictly adheres to a single source of truth:

```
                      FormatPolicyRegistry (format_policy.py)
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
           GET /capabilities              watermarks capabilities
                    │                                 │
                    └────────────────┬────────────────┘
                                     ▼
                     docs/capabilities.md (10-col table)
                                     ▲
                                     │ (verified by)
               tests/test_docs_capabilities_consistency.py
```

- **Format Registry**: Authoritative definition of canonical policies, extensions, inspection capabilities, cleaning capabilities, verify capabilities, supported modes, fidelity levels, and optional dependencies.
- **Runtime Services**: Both CLI `watermarks capabilities` and HTTP `GET /capabilities` generate output directly from `FormatPolicyRegistry.get_default()`.
- **Public Documentation**: `docs/capabilities.md` renders the exact policy matrix using a controlled, machine-parsable table.
- **Consistency Enforcement**: Automated tests parse the markdown documentation and assert 1-to-1 parity against the live registry and endpoint schemas.

---

## 3. Format Policy & Alias Accounting

Empirical audit of `FormatPolicyRegistry.get_default()`:

| Metric | Measured Value | Verification Method |
|:---|:---|:---|
| **Canonical Policies** | **23** | `len(FormatPolicyRegistry.get_default().all_policies())` |
| **Total Registered Extensions** | **37** | Set union of all policy `extensions` |
| **Extension Aliases (Beyond 1-per-policy)** | **14** | `37 total extensions - 23 canonical policies` |
| **Non-Identity Extensions** (`ext != format_name`) | **16** | 6 audio (`.mp3`, `.wav`, `.flac`, `.aac`, `.ogg`, `.m4a`), 5 video (`.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`), 1 html (`.htm`), 1 jpeg (`.jpg`), 1 latex (`.tex`), 1 md (`.markdown`), 1 tiff (`.tif`) |
| **Runtime-Available Policies** | **22** | Core standard library execution |
| **Dependency-Sensitive Policies** | **1** | `pdf` (Model B bounded fallback; requires `ghostscript`, `qpdf`, `c2patool` for deep cleaning) |
| **Verify-Supported Policies** | **3** | `docx`, `xlsx`, `pptx` |
| **Safe-Mode Only Policies** | **1** | `svg` (`supported_modes = ('safe',)` strictly) |
| **Multi-Mode Policies** | **22** | `safe, balanced, aggressive` |

---

## 4. Contract Parity & Consistency Audit

### 4.1 Registry ↔ /capabilities ↔ Docs Parity
- **Exact Canonical Policy Set**: All 23 policies match between registry, `/capabilities`, and `docs/capabilities.md`.
- **Extension Set**: All 37 extensions map to their respective canonical policy without duplicate mappings.
- **Verify Capabilities**: Only `docx`, `xlsx`, and `pptx` expose verification; all other 20 policies explicitly declare `NONE`.
- **Fidelity Levels**: Exact adherence to `FidelityLevel` enum (`LEVEL_A`, `LEVEL_B`, `LEVEL_C`, `LEVEL_D`).

### 4.2 Resource & Size Limits Parity
All documented limits match production constants:

| Limit Description | Documented Value | Production Constant | Assertion Status |
|:---|:---|:---|:---|
| Top-level file input | `256 MiB` | `common.MAX_INPUT_BYTES` (268,435,456 B) | **MATCH** |
| CLI stdin stream | `64 MiB` | `common.MAX_STDIN_BYTES` (67,108,864 B) | **MATCH** |
| HTTP input payload | `256 MiB` | `server.MAX_INPUT_BYTES` (268,435,456 B) | **MATCH** |
| HTTP request body | `384 MiB` | `server.MAX_BODY_BYTES` (402,653,184 B) | **MATCH** |
| Batch single-file ceiling | `32 MiB` | `batch_processor.MAX_INPUT_BYTES` (33,554,432 B) | **MATCH** |
| Batch aggregate ceiling | `200 MiB` | `batch_processor.MAX_BATCH_TOTAL_BYTES` (209,715,200 B) | **MATCH** |
| CLI Batch file count | `100` | `batch_processor.MAX_BATCH_FILES` (100) | **MATCH** |
| HTTP /batch Request file count | `50` | `server.MAX_BATCH_FILES` (50) | **MATCH** |
| Batch inline output ceiling | `32 MiB` | `batch_processor.MAX_BATCH_INLINE_OUTPUT_BYTES` (33,554,432 B) | **MATCH** |
| ZIP member count | `10,000` | `security.SecurityLimits.max_member_count` | **MATCH** |
| ZIP member uncompressed | `64 MiB` | `security.SecurityLimits.max_member_uncompressed_bytes` (67,108,864 B) | **MATCH** |
| ZIP total uncompressed | `128 MiB` | `security.SecurityLimits.max_total_uncompressed_bytes` (134,217,728 B) | **MATCH** |
| Decompression ratio | `100x` | `security.SecurityLimits.max_compression_ratio` (100.0) | **MATCH** |
| XML part byte ceiling | `32 MiB` | `security.SecurityLimits.max_xml_part_bytes` (33,554,432 B) | **MATCH** |
| XML aggregate byte ceiling | `128 MiB` | `security.SecurityLimits.max_total_xml_bytes` (134,217,728 B) | **MATCH** |
| XML max depth | `100` | `security.SecurityLimits.max_xml_depth` | **MATCH** |
| XML max elements | `500,000` | `security.SecurityLimits.max_xml_elements` | **MATCH** |

### 4.3 Exit Code & Batch Contract Parity
- **0 `SUCCESS`**: Single-file success or no mutation needed.
- **2 `UNSUPPORTED`**: Strictly reserved for the unsupported format family. Never maps to limits or setup failure.
- **3 `VALIDATION_FAILED`**: Post-clean invariant checks failed; file rolled back.
- **4 `INVALID_INPUT`**: Missing input file, zero input files found, or invalid configuration.
- **5 `DEPENDENCY_MISSING`**: Required runtime external binary missing.
- **6 `LIMIT_EXCEEDED`**: Input size, batch count, batch total, or archive structural limit breached.
- **7 `BATCH_PARTIAL_FAILURE`**: Additive batch exit code indicating mixed results (aliased to `BATCH_PARTIAL_SUCCESS`).
- **10 `INTERNAL_ERROR`**: Unhandled exception or fatal server fault.

### 4.4 HTTP API Status Parity
Matches `error_code_to_http_status()`:
- `UNSUPPORTED_FORMAT` -> **415**
- `INVALID_CONTAINER` -> **400**
- `VALIDATION_FAILED` -> **422**
- `OPTIONAL_DEPENDENCY_MISSING` -> **424**
- `UNSUPPORTED_ARCHIVE_FEATURE` -> **422**
- `PROCESSING_LIMIT_EXCEEDED` -> **413**
- `INTERNAL_ERROR` -> **500**

### 4.5 Status Terminology & Semantics
- **`NOT_CHECKED` vs `NOT_DETECTED`**: Distinct and non-interchangeable. A `NOT_CHECKED` surface is not verified.
- **`NO_CHANGE_REQUIRED` Scope**: Explicitly documented as "no authorized mutation planned for checked/supported surfaces"; not a universal guarantee that every proprietary carrier is absent.
- **PDF Model B Bounded Fallback**: Explicitly documented that stdlib inspects/cleans standard metadata dictionaries, but deep raster inpainting or attachment distillation returns `OPTIONAL_DEPENDENCY_MISSING` (exit 5 / HTTP 424) if optional tools are missing. It never returns `NO_CHANGE_REQUIRED`.

### 4.6 Semantic Truthfulness Closures
- **Resource Limits vs Archive Features**: Numeric resource limits (ZIP count/sizes, XML depth/sizes/elements) trigger `PROCESSING_LIMIT_EXCEEDED` (CLI Exit 6 / HTTP 413). Unsupported archive features (e.g. ZIP64, ZipSlip, encrypted members) trigger `UNSUPPORTED_ARCHIVE_FEATURE` (CLI Exit 4 / HTTP 422). Malformed structures trigger `INVALID_CONTAINER` (CLI Exit 4 / HTTP 400).
- **Contextual Unicode Preservation**: `U+200C` and `U+200D` are **not** unconditionally stripped. Contextually legitimate joiners (emoji ZWJ sequences across emoji bases, Arabic/Persian/Devanagari script shaping joiners) are preserved as `action == "keep"`. Only isolated, unattached, or covert watermark carrier occurrences are pruned.
- **Canonical Audio/Video Cleaning**: Canonical `watermarks clean` for audio (WAV, MP3, FLAC) and video (MP4) is **100% in-process** via `clean_av()` without spawning subprocesses or requiring `ffmpeg`. The `ffmpeg` dependency and `audio_watermark_notch` operation are strictly reserved for standalone external purifiers or the HTTP service option `remove_audio_watermark`.
- **XLSX Shared-String Invariants**: Shared strings are updated in place within their existing `<si>` positions without re-indexing or deduplication. Shared-string indices and referring cell indices (`<c t="s"><v>N</v></c>`) remain unchanged.
- **Phase 4 Commit Provenance**: Canonical Phase 4 evidence/docs closure is `1fb5cba5ef243021bf53ef4f1498aedf76ccfa16` (amended from historical pre-amend commit `3370fcc7b0ef0002c30748d410293e32cd790dd0`).
- **Phase 12 Commit Provenance**:
  - Documentation implementation commit: `c6a4b3a4a98404a9e4070a2719a997ecab7289ee` (commit `c6a4b3afbc1d58e30d39202746449f089735bb3d`)
  - Semantic truthfulness closure commit: `2e4e31c8a15230c41e5089cd52838c6e8d324549`

### 4.6 Clean Hygiene Audits
- **CLI Command Syntax**: All CLI invocations in `README.md` use valid subcommands (`inspect`, `clean`, `batch`, `verify`, `capabilities`) and real options (`--mode`, `--json`, `--dry-run`, `--in-place`, `-o`, `-r`, `--output-dir`, `--reports-dir`).
- **Relative Markdown Links**: 100% of relative links across `README.md`, `docs/capabilities.md`, and `docs/format_guarantees.md` resolve to existing targets (0 broken links).
- **Sensitive Local Paths**: 0 occurrences of private host usernames, local development directories, or absolute paths (`nvhoa`, `C:\Users`, `e:\wartermark_remove`).
- **Hyperbolic / Unproven Claims**: 0 occurrences of prohibited marketing claims ("removes all AI watermarks", "100% secure", "guarantees no watermark remains", "pixel-perfect", "blazing fast").

---

## 5. Test Verification Summary

| Suite | Scope | Target Baseline | Result | Status |
|:---|:---|:---|:---|:---|
| **Phase 12 Consistency** | `tests/test_docs_capabilities_consistency.py` | 11 passed | **17 passed in 0.25s** | **PASS** |
| **Capabilities Contract** | `tests/test_capabilities_endpoint.py`, `tests/test_cli_v21.py`, `tests/test_api_v21.py` | 35 passed | **35 passed in 3.79s** | **PASS** |
| **Phase 4 Batch Contract** | `tests/test_batch_contract_closure.py` | 23 passed | **23 passed in 2.46s** | **PASS** |
| **Phase 9 Security** | `tests/test_malformed_archives.py` | 141 passed | **141 passed in 1.46s** | **PASS** |
| **Phase 10 Idempotence** | `tests/test_idempotence.py`, `tests/test_property_unicode.py` | 139 passed | **139 passed in 11.35s** | **PASS** |
| **Format Lossless Regr.** | `tests/test_docx_body_carriers.py`, `tests/test_xlsx_lossless.py`, `tests/test_pptx_lossless.py` | 135 passed | **135 passed in 22.00s** | **PASS** |
| **Performance Harness** | `tests/test_performance_harness.py` | 11 passed | **11 passed in 50.34s** | **PASS** |
| **Canonical Full Pytest** | Complete test repository (`pytest -ra`) | 1946 passed, 152 skipped | **1952 passed, 152 skipped in 198.43s** | **PASS** |

- **Warnings**: 0
- **Failures**: 0

---

## 6. Frozen Core Integrity Verification

```bash
git diff v2.0.0 -- service/scripts/docx/
```
**Diff Output**: `EMPTY` (0 lines changed).

### Cryptographic Fingerprints
- **Golden DOCX SHA256**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (**MATCH**)
- **Candidate DOCX SHA256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (**MATCH**)

---

## 7. Production Source Changes

**NONE**. No production code files in `service/` or `service/scripts/` were modified. All additions were restricted to documentation (`README.md`, `docs/capabilities.md`, `docs/format_guarantees.md`, `docs/v2.1/PHASE12_DOCUMENTATION_REPORT.md`, `docs/v2.1/ROADMAP.md`) and automated consistency test code (`tests/test_docs_capabilities_consistency.py`).
