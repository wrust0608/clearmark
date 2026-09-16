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
1. `SAFE` (Default for all formats, strictly mandatory for structured formats like DOCX/XLSX/PPTX):
   - High-confidence metadata and provenance scrubbing.
   - Invisible Unicode removal with contextual preservation (emoji sequences, bidi controls, Arabic shaping, Devanagari).
   - Zero destructive whitespace normalization (e.g. `normalize_spaces = False` in DOCX).
   - Zero semantic or LLM rewrites.
   - Strict runtime invariant validation.
2. `BALANCED`:
   - Extends detection to secondary heuristic markers.
   - Still strictly maintains semantic and structural document invariants.
3. `AGGRESSIVE`:
   - Only permitted where format policy explicitly enables it.
   - Generates explicit warnings.
   - Never bypasses structural/fidelity validation on container formats.

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
