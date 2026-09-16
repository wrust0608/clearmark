# ARCHITECTURE DECISION RECORDS (ADR) — ClearMark v2.1

> **Status**: Frozen Baseline / Design Stage  
> **Development Line**: `v2.1-dev`  
> **Reference Baseline**: `v2.0.0` (`758d3085b8868566209a82ea981a32aa61147a44`)  
> **Upstream Release**: `v0.7.0` (`41ef353afd8ff354905c25abb803ae964d06d3d9`)

---

## ADR-001: Preservation and Isolation of the v2.0 Lossless DOCX Core

### Context
v2.0.0 successfully designed, verified, and independently audited the Lossless DOCX Subsystem. It achieved:
- Zero visible text deviation (100.000% string identity);
- Invariant paragraph count (204 -> 204) and run count (288 -> 288);
- Invariant manual page breaks (5 -> 5) and rendered pages (19 -> 19);
- Strict raw OPC ZIP preservation (byte-for-byte identity of all non-target compressed payloads and ZipInfo metadata);
- 19/19 pixel-identical visual page rendering against the True Golden baseline.

### Decision
The core DOCX engine located in `service/scripts/docx/` is **FROZEN**.
1. No refactoring for style, code brevity, or micro-optimization is permitted.
2. The core may only be modified if a reproducible bug is identified, preceded by a failing regression test, and must still pass all v2.0 Golden regression benchmarks.
3. The rest of the application will interface with DOCX solely via the public entry points (`DocxPackage`, `DocxDetector`, `DocxMutationPlan`, `DocxPatcher`, `DocxFidelityValidator`, `clean_docx_lossless`).

---

## ADR-002: Unified Processing Pipeline Architecture

### Context
Upstream v0.7.0 and previous iterations scattered inspection, cleaning, and normalization logic across disparate scripts (`clean_file.py`, `inspect_file.py`, `container_meta.py`, `image_meta.py`, `text_unicode.py`, and `server.py`). Different formats exhibited diverging CLI arguments, inconsistent JSON payloads, and varying error behaviors.

### Decision
All formats must adhere to a single standard lifecycle pipeline:
```
INPUT
  ↓
FORMAT DETECTION
  ↓
INSPECTION (Non-destructive)
  ↓
FORMAT POLICY RESOLUTION
  ↓
MUTATION PLAN GENERATION
  ↓
CLEAN / MINIMAL PATCH
  ↓
VALIDATE (Runtime Invariant Check)
  ↓
REPORT GENERATION
  ↓
OUTPUT (Safe atomic write)
```

Every format operation reports one of the canonical states:
- `INSPECTED`: File examined; findings cataloged; no modifications attempted.
- `NO_CHANGE_REQUIRED`: No supported markers or carrier artifacts found; output remains identical.
- `CLEANED`: High-confidence markers removed; runtime validation succeeded.
- `VALIDATION_FAILED`: Proposed mutations violated document invariants; output aborted; original untouched.
- `UNSUPPORTED`: Container, archive feature, or format is not currently supported; fail-closed.
- `ERROR`: Input is malformed, hostile, or exceeded configured safety boundaries.

---

## ADR-003: First-Class Inspection-First Workflow & Dry-Run Semantics

### Context
Users and automated pipelines need to know *what* metadata, C2PA claims, or invisible Unicode sequences exist in a file *before* modifying or committing to cleaning.

### Decision
1. Inspection must always be zero-mutation and read-only.
2. `--dry-run` performs inspection, policy evaluation, mutation planning, and validation feasibility checks without writing any file to disk or modifying the original.
3. Terminology is strictly honest:
   - "Detected marker/provenance surface" (when a concrete detector finds an identifiable marker).
   - "No supported marker detected" (when no known markers are found).
   - "Not checked" / "Unknown" (when optional dependencies or detectors are missing).
   - Absolute marketing claims like "watermark found" or "100% removed" are strictly prohibited.

---

## ADR-004: Standardized Structured Cleaning Report (`CleaningReport`)

### Context
Different endpoints previously returned incompatible dictionary shapes (`to_dict()`, `actions`, `still_has_c2pa`, etc.).

### Decision
A unified data schema (`CleaningReport`) is established for CLI, HTTP API, and batch logs:
- `input`: filename, format, size_bytes, sha256
- `inspection`: findings[], detectors_run[], detectors_unavailable[]
- `policy`: mode (`SAFE` | `BALANCED` | `AGGRESSIVE`), format_policy, normalize_spaces, remote_processing
- `mutation_plan`: mutations[], changed_parts[]
- `validation`: status (`PASS` | `FAIL` | `SKIPPED`), invariants, warnings[]
- `output`: changed (bool), size_bytes, sha256, path
- `privacy`: network_used (bool), external_services[]
- `performance`: elapsed_ms

> **Constraint**: To prevent massive memory overhead and data leakage, document body text must never be stored inside the report.

---

## ADR-005: Explicit Processing Modes (`SAFE`, `BALANCED`, `AGGRESSIVE`)

### Context
Different document types and threat models require different trade-offs between carrier removal and typographical risk.

### Decision
Three explicit modes are defined:
1. `SAFE`:
   - Mandatory supported baseline for all formats.
   - Default for all formats.
   - Default for structured document formats (DOCX, XLSX, PPTX).
   - High-confidence metadata and provenance scrubbing.
   - Invisible Unicode removal with contextual preservation (emoji sequences, bidi controls, Arabic shaping, Devanagari).
   - Zero destructive whitespace normalization (e.g. `normalize_spaces = False` in DOCX).
   - Zero semantic or LLM rewrites.
   - Strict runtime invariant validation.
2. `BALANCED` / `AGGRESSIVE`:
   - Available only where `FormatPolicy` explicitly permits them (`supported_modes`).
   - Must retain semantic and structural document invariants.
   - Must never bypass fidelity validation on container or structured document formats.
   - Unsupported extra behavior must produce an explicit warning rather than silently pretending to perform a stronger clean.

---

## ADR-006: Dedicated Lossless Adapters for XLSX and PPTX

### Context
XLSX and PPTX are ZIP-based OOXML formats like DOCX, but their internal XML hierarchies differ fundamentally:
- XLSX relies on `sharedStrings.xml`, worksheet sheet data, formula definitions, cell styling, calculation chains, and drawing relationships.
- PPTX relies on slide hierarchies, slide layouts, slide masters, shape trees, and presentation properties.

### Decision
Do **NOT** reuse DOCX XML stripping rules directly.
Create independent, format-specific lossless adapters:
- `service/scripts/xlsx/` (Phase 7)
- `service/scripts/pptx/` (Phase 8)
Both adapters must replicate the `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE` paradigm, preserving non-target member payloads byte-for-byte in raw compressed form.

---

## ADR-007: Safe File Output & Atomic Replacement

### Context
Overwriting original files in-place risks permanent data loss if a process crashes, runs out of disk space, or fails validation.

### Decision
1. **Default**: Never overwrite source files. Output is written to a designated output file or alongside the source using collision-safe naming (`filename.cleaned.ext`).
2. **In-place mode (`--in-place`)**:
   - Write to a sibling temporary file (`filename.tmp.<pid>.<uuid>`).
   - Run runtime invariant validation.
   - On validation success: flush/fsync and atomically replace the original (`os.replace`).
   - On validation failure: immediately delete the temporary file and leave the original completely untouched.

---

## ADR-008: Fail-Closed Security & Container Hardening

### Context
Hostile, truncated, or malformed archives can trigger denial of service, directory traversal, or memory exhaustion.

### Decision
The system enforces strict fail-closed boundaries:
- **ZipSlip**: All member paths must resolve within the intended archive tree; absolute paths and `../` components are rejected.
- **ZipBomb**: Decompressed size limits and compression ratios are validated up-front.
- **XML Security**: Deep nesting limits, entity expansion limits, and oversized XML member caps are strictly enforced.
- **Unsupported Archive Features**: Truncated headers, duplicate member names, unsupported compression methods, encrypted members, and complex ZIP64 edge cases must fail closed with an explicit machine-readable error code (`UNSUPPORTED_ARCHIVE_FEATURE` or `INVALID_CONTAINER`). Silent normalizations or repairs are prohibited.

---

## ADR-009: Idempotence Guarantee

### Context
Re-running watermark cleaning on an already cleaned file must not cause incremental deterioration or endless recompression.

### Decision
For any valid input file $X$:
1. $X_{clean} = \text{clean}(X)$
2. $\text{clean}(X_{clean}) == X_{clean}$
3. The second execution must explicitly return status `NO_CHANGE_REQUIRED`.

---

## ADR-010: Temporary Format Policy Compatibility Forwarder in pipeline_types.py

### Context
During Phase 1, `FormatPolicy` and `FormatPolicyRegistry` were consolidated into `service/scripts/format_policy.py` as the authoritative single source of truth. To preserve backward compatibility for callers importing from `pipeline_types` without causing circular imports or code duplication, dynamic `__getattr__` resolution was introduced in `service/scripts/pipeline_types.py`.

### Decision
1. The dynamic `__getattr__` in `service/scripts/pipeline_types.py` is strictly a **temporary compatibility alias** for `FormatPolicy`, `FormatCapabilities`, and `FormatPolicyRegistry`.
2. Do **NOT** extend this pattern. No additional service-layer objects or runtime business logic may be exposed through `pipeline_types.__getattr__`.
3. `service/scripts/pipeline_types.py` must remain strictly data-model focused (dataclasses, enums, report serialization schemas).
4. In Phase 3, all internal modules (`cli.py`, `server.py`, `pipeline.py`, `clean_file.py`, `inspect_file.py`) were migrated to direct imports from `service/scripts/format_policy.py`. The `pipeline_types.__getattr__` forwarder issues a `DeprecationWarning` when accessed to maintain backward compatibility for external callers while signaling deprecation.

---

## ADR-011: Canonical CLI Grammar, Exit Code Contract, and HTTP API Normalization

### Context
v2.0 and earlier relied on fragmented entry points (`clean_file.py`, `inspect_file.py`) and ad-hoc HTTP endpoints (`/clean`, `/inspect`) with varying exit codes, custom dictionary serialization, and inconsistent error status codes.

### Decision
1. **Canonical CLI Grammar (`service/scripts/cli.py`)**:
   - Subcommands: `inspect`, `clean`, `verify`, `capabilities`.
   - Public flags: `--mode {safe,balanced,aggressive}`, `--dry-run`, `--in-place`, `--output <path>`, `--json`.
   - Batch commands are explicitly reserved for Phase 4.
2. **Stable Exit Code Contract**:
   - `0`: Success (inspected, cleaned, or verified with NO_CHANGE_REQUIRED / CLEANED / INSPECTED / PASS).
   - `2`: Unsupported format or capability (`UNSUPPORTED_FORMAT`, `UNSUPPORTED_ARCHIVE_FEATURE`).
   - `3`: Document invariant validation failed (`VALIDATION_FAILED`).
   - `4`: Invalid CLI arguments or malformed/unparseable container input (`INVALID_CONTAINER`).
   - `5`: Optional dependency missing (`OPTIONAL_DEPENDENCY_MISSING`).
   - `6`: Processing resource limit exceeded (`PROCESSING_LIMIT_EXCEEDED`).
   - `10`: Unhandled internal error (`INTERNAL_ERROR`).
3. **JSON Output Discipline**:
   - When `--json` is supplied, stdout contains solely the canonical JSON serialization of `CleaningReport` (or `capabilities` / `verify` outcome).
   - Diagnostic prints, progress prose, and deprecation warnings route exclusively to stderr.
4. **HTTP Status Code Mapping**:
   - `ErrorCode.UNSUPPORTED_FORMAT` -> `415 Unsupported Media Type`
   - `ErrorCode.INVALID_CONTAINER` -> `400 Bad Request`
   - `ErrorCode.VALIDATION_FAILED` -> `422 Unprocessable Entity`
   - `ErrorCode.OPTIONAL_DEPENDENCY_MISSING` -> `424 Failed Dependency`
   - `ErrorCode.UNSUPPORTED_ARCHIVE_FEATURE` -> `422 Unprocessable Entity`
   - `ErrorCode.PROCESSING_LIMIT_EXCEEDED` -> `413 Content Too Large`
   - `ErrorCode.INTERNAL_ERROR` -> `500 Internal Server Error`
5. **Authoritative Capabilities Source**:
   - `GET /capabilities` generates its format capabilities dynamically from `FormatPolicyRegistry` in `service/scripts/format_policy.py`. Hardcoding capability matrices in HTTP handlers is prohibited.
6. **Legacy Compatibility**:
   - Legacy scripts `service/scripts/clean_file.py` and `service/scripts/inspect_file.py` are preserved as compatibility wrappers emitting deprecation notices to stderr.
   - HTTP `/clean` preserves the legacy response envelope (`{"cleaned": base64, "report": {...}}`) containing backward-compatible legacy summary keys alongside the structured canonical `CleaningReport`.

---

## ADR-012: Isolated Batch Processing Engine Architecture

### Context
Users and programmatic consumers require processing multiple explicit files or entire directory trees safely and deterministically. Prior iterations lacked batch capabilities or ran ad-hoc loops where a single malformed file aborted entire workflows, output files collided or overwrote originals, and state or memory leaked across files.

### Decision
1. **Batch Processor Abstraction (`service/scripts/batch_processor.py`)**:
   - `BatchProcessor` orchestrates batch runs using the canonical `Pipeline` (`Pipeline.clean`, `Pipeline.inspect`). Format detection, cleaning, inspection, validation, and policy logic are strictly reused—never duplicated.
2. **File-Level Failure Isolation**:
   - Every file is processed within an isolated item boundary with its own fresh `Pipeline` instance.
   - An error in file $i$ (e.g., malformed container, hostile bytes, unsupported format) is recorded in `BatchItemResult` with status `ERROR`, `INVALID_CONTAINER`, or `UNSUPPORTED`. It **NEVER** halts or aborts execution of files $i+1 \dots N$.
3. **Partial-Success Semantics**:
   - A batch containing both successful and failed files completes successfully at the infrastructure level.
   - Outputs for successful items are committed atomically and remain available; failure of a sibling file never deletes or rolls back successful outputs.
4. **Deterministic Ordering**:
   - Explicit CLI file arguments preserve the exact user-specified order.
   - Directory input discovery (`--recursive` optional) applies a stable, platform-independent lexical sort on normalized relative paths (`str(p.relative_to(root)).replace("\\", "/")`).
   - `BatchReport.items` order strictly corresponds to execution order.
5. **Output Directory & Collision Policy**:
   - Batch output never overwrites input originals.
   - When `--output-dir` is provided, directory input batches preserve their relative sub-directory tree structure.
   - Sibling or cross-directory name collisions are resolved deterministically using suffixes: `<stem>.cleaned.<ext>`, `<stem>.cleaned.1.<ext>`, `<stem>.cleaned.2.<ext>`.
   - Pre-existing files in the output directory are never overwritten.
   - Failed, unsupported, or dry-run items write **zero** output files to disk; temporary files are removed immediately.
6. **Batch Exit Code Contract**:
   - `0`: Complete success (all items resulted in `CLEANED`, `NO_CHANGE_REQUIRED`, or `INSPECTED`).
   - `1`: Partial success (at least one item failed validation, encountered an error, or was unsupported, but batch completed).
   - `2`: Fatal batch setup error (e.g., zero valid inputs, invalid CLI arguments, or root-level batch limits exceeded before processing).
7. **Mathematical Reconciliation & Honest Summary Invariant**:
   - Every `BatchReport` must satisfy:  
     `total == cleaned + no_change + inspected + unsupported + validation_failed + errors + skipped`
   - In dry-run mode, items are classified as `INSPECTED` (`summary.inspected`), and `output.changed == False` while `output.would_change == True`. Previewed changes are never counted as cleaned.
8. **Sequential Execution & Resource Safety**:
   - Processing is sequential by default to ensure determinism, failure isolation, and bounded memory consumption.
   - Root-level limits (`WATERMARKS_MAX_BATCH_FILES`, `WATERMARKS_MAX_BATCH_TOTAL_BYTES`) fail fast before processing to protect host resources.
9. **Zero-Network & Privacy Invariant**:
   - Local batch processing performs 0 network calls.
   - `BatchReport` and per-file JSON reports contain metadata only; document body text dumps are strictly prohibited.
10. **Strict Metadata-Only Report Model & Transport Envelope Separation**:
   - `BatchReport` and `BatchItemResult` serialize strictly metadata, hashes, timings, format, status, and safe error codes.
   - Cleaned file payloads and base64 strings are **never** part of canonical `BatchReport`.
   - HTTP `POST /batch` delivers cleaned files via an explicit transport envelope: `{"ok": true, "report": BatchReport, "outputs_included": bool, "output_delivery": str, "outputs": [...]}`.
   - CLI `watermarks batch ... --json` and `--reports-dir` emit metadata-only JSON.
11. **HTTP Inline Response Bounds vs. Input Acceptance**:
   - Input batch acceptance limit (`WATERMARKS_MAX_BATCH_TOTAL_BYTES`, default 200 MiB) is strictly distinct from the inline output response limit (`WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES`, default 32 MiB).
   - To prevent severe memory amplification (~6x overhead: decoded inputs + cleaned outputs + base64 strings + JSON string copies > 1.2 GiB RAM on a 200 MiB batch), cumulative cleaned output size is evaluated *before* calling `base64.b64encode`.
   - If cumulative cleaned output exceeds `WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES`, base64 encoding is skipped entirely and the response returns `outputs_included: false`, `output_delivery: "not_available_inline"` alongside the complete canonical `BatchReport`.

