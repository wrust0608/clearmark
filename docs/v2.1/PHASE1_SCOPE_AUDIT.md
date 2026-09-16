# Phase 1 Scope Audit & Normalization Report

**Document Version:** 1.0.0  
**Branch:** `v2.1-dev`  
**Baseline Commit:** `758d3085b8868566209a82ea981a32aa61147a44` (v2.0.0)  
**Phase 1 Commit:** `a57cd66`  
**Status:** AUDIT COMPLETE — PHASE 1 NORMALIZED

---

## 1. Executive Summary

Feature development was immediately halted per instructions. An exhaustive audit of the Phase 1 implementation was conducted to:
1. Verify the absolute freeze of the v2.0 lossless DOCX subsystem (`service/scripts/docx/`).
2. Catalog and classify all newly introduced capabilities against the approved 15-phase roadmap (Phase 0 through Phase 14).
3. Eliminate duplicate policy registry implementations and establish `service/scripts/format_policy.py` as the **single source of truth**.
4. Enforce that `service/scripts/pipeline_types.py` remains strictly data-only (dataclasses, enums, report serialization).
5. Audit atomic in-place writing, read-only inspection, dry-run mode, report privacy, and idempotence boundaries.
6. Defer acceptance of early-implemented features to their designated roadmap phases without removing verified working code.

---

## 2. Frozen Subsystem & Baseline Verification

### 2.1 DOCX Core Subsystem Integrity
A direct diff against tag `v2.0.0` was executed:
```bash
git diff v2.0.0 -- service/scripts/docx/
```
**Result:** `0` changes (`NONE`). The frozen Lossless DOCX engine is 100% untouched.

### 2.2 Golden Fixture & Canonical Candidate Verification
```bash
git diff v2.0.0 -- 01_GOLDEN_ORIGINAL_UNTOUCHED.docx 04_CANDIDATE_LOSSLESS_OUTPUT.docx
```
**Result:** `0` changes (`NONE`). Binary files match verified hashes:
- `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (49,959 bytes)
- `04_CANDIDATE_LOSSLESS_OUTPUT.docx`: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (49,395 bytes)

### 2.3 Legacy Entry Points Backward Compatibility
The legacy entry points were checked against `v2.0.0`:
- `clean_file.py`: Unmodified, operational.
- `inspect_file.py`: Unmodified, operational.
- `service/scripts/container_meta.py`: Unmodified, operational.
- `service/main.py` (`HTTP /clean`): Unmodified, operational.

The unified pipeline engine (`service/scripts/pipeline.py`) operates in parallel and does not prematurely replace any public interfaces.

---

## 3. Scope Classification of Phase 1 Implementation

Each newly introduced behavior and artifact has been audited and classified:

| Component / Behavior | Location | Classification | Notes & Scope Boundary |
| :--- | :--- | :--- | :--- |
| **CleaningReport Schema** | `pipeline_types.py` | `PHASE_1_REQUIRED` | Universal JSON-serializable report. Zero document text stored. |
| **Pipeline Lifecycle States** | `pipeline_types.py` | `PHASE_1_REQUIRED` | `INSPECTED`, `NO_CHANGE_REQUIRED`, `CLEANED`, `VALIDATION_FAILED`, `UNSUPPORTED`, `ERROR`. |
| **Standard Error Codes** | `pipeline_types.py` | `PHASE_1_REQUIRED` | `UNSUPPORTED_FORMAT`, `INVALID_CONTAINER`, `VALIDATION_FAILED`, etc. |
| **Processing Modes & Fidelity** | `pipeline_types.py` | `PHASE_1_REQUIRED` | Enums: `SAFE`, `BALANCED`, `AGGRESSIVE`; Levels: `LEVEL_A` through `LEVEL_D`. |
| **Specification Naming Aliases**| `pipeline_types.py` | `PHASE_1_REQUIRED` | Aliases: `ProcessingStatus`, `InputInfo`, `InspectionReport`, `MutationSummary`, `ValidationReport`, `OutputInfo`, `PrivacyReport`. |
| **Format Policy Registry** | `format_policy.py` | `PHASE_1_REQUIRED` | Single authoritative source of truth: `FormatPolicy`, `FormatCapabilities`, `FormatPolicyRegistry`. |
| **Dynamic Policy Forwarder** | `pipeline_types.py` | `PHASE_1_REQUIRED` | Safe `__getattr__` forwarding to `format_policy.py` preventing circular imports and duplicate registries. |
| **Pipeline Engine Orchestrator**| `pipeline.py` | `PHASE_1_REQUIRED` | Top-level coordinator consuming `FormatPolicyRegistry`. Dispatches to frozen format engines. |
| **DOCX Subsystem Dispatch** | `pipeline.py` | `PHASE_1_REQUIRED` | Calls `DocxDetector` and `clean_docx_lossless` without duplicating mutation logic. |
| **CleaningReport Privacy Invariant** | `pipeline_types.py`, `tests` | `PHASE_1_REQUIRED` | Confirmed: no full document text, paragraphs, or body strings stored. Tested against Golden document phrases. |
| **Pipeline.inspect() Method** | `pipeline.py` | `PHASE_1_SUPPORTING` | Read-only inspection generating `InspectionData` for `CleaningReport`. Does not mutate input. Full CLI/HTTP integration deferred to Phase 2. |
| **Pipeline.clean() Execution** | `pipeline.py` | `PHASE_1_REQUIRED` | End-to-end execution verifying data model against frozen DOCX engine. |
| **dry_run=True Parameter** | `pipeline.py` | `IMPLEMENTED_EARLY_FOR_PHASE_2` | Implemented early in engine skeleton. Acceptance deferred to Phase 2 (pending CLI/HTTP wiring and preview semantics). |
| **in_place=True Replacement** | `pipeline.py` | `IMPLEMENTED_EARLY_FOR_PHASE_3` | Implemented early via `safe_write_bytes` (sibling temp, flush, fsync, atomic `os.replace`). Acceptance deferred to Phase 3. |
| **DOCX Idempotence Detection** | `pipeline.py` | `IMPLEMENTED_EARLY_FOR_PHASE_10`| Returns `NO_CHANGE_REQUIRED` on already cleaned DOCX. Acceptance deferred to Phase 10 (pending multi-format property tests). |

---

## 4. Single Source of Truth Audit: Format Policy Registry

### 4.1 Identified Issue
In initial Phase 1 development, `FormatPolicyRegistry` was implemented in `service/scripts/pipeline_types.py` and then duplicated into `service/scripts/format_policy.py`.

### 4.2 Normalization Applied
1. **Authoritative Location:** `service/scripts/format_policy.py` is the single source of truth for:
   - `FormatCapabilities`
   - `FormatPolicy`
   - `FormatPolicyRegistry`
   - Per-format policies across all document, image, vector, audio, video, and text types.
2. **Data-Only Separation:** `service/scripts/pipeline_types.py` was stripped of duplicate class definitions. It contains solely data models, report dataclasses, lifecycle enums, and specification aliases.
3. **Consumer Decoupling:** `service/scripts/pipeline.py` imports `FormatPolicy` and `FormatPolicyRegistry` directly from `format_policy.py`.
4. **Verification Test:** `test_format_policy_single_source_of_truth` in `tests/test_pipeline_data_model.py` asserts:
   - `pipeline_types.FormatPolicyRegistry is format_policy.FormatPolicyRegistry`
   - `pipeline_types.FormatPolicy is format_policy.FormatPolicy`
   - Registry instances contain complete policies for `docx`, `xlsx`, `pdf`, `png`, etc.

---

## 5. Report Privacy & Data Leakage Audit

Per Section 13, `CleaningReport` must store:
- Hashes (SHA-256)
- Component counts (paragraphs, runs, breaks)
- OPC part names (`docProps/app.xml`, `customXml/item1.xml`)
- Codepoint markers (e.g. `U+200B ZERO WIDTH SPACE`)
- Structural metrics and invariant statuses

It must **NEVER** store:
- Full document body text or paragraphs
- Large extracted content
- User text payloads

### 5.1 Verification Test
`test_cleaning_report_privacy_regression_scanning_golden_fixture` scans the serialized JSON from both `inspect()` and `clean()` of `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`. It confirms that known document phrases ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", "Độc lập - Tự do - Hạnh phúc", "BÁO CÁO", "chất lượng công trình", "nghiệm thu", "chủ đầu tư", "thi công", "tiêu chuẩn") do not appear anywhere in the serialized reports (case-sensitive and case-insensitive).

---

## 6. Atomic In-Place Writing Audit

The `in_place=True` option in `pipeline.py` delegates to `safe_write_bytes()` in `service/scripts/common.py`:
1. Checks destination is not a symlink.
2. Creates sibling temporary file in destination directory via `tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(parent))`.
3. Writes payload bytes.
4. Flushes stream buffers (`f.flush()`).
5. Commits to disk (`os.fsync(f.fileno())`).
6. Atomically replaces original file (`os.replace(tmp_name, dest)`).
7. On any exception, unlinks temporary file and leaves the original untouched.

**Status:** Implementation verified safe and correct; formal public acceptance deferred to Phase 3 (CLI/API normalization).

---

## 7. Evidence Citations & Fidelity Policy

Per Section 14:
- The command `tools/verify_document_fidelity.py ... --no-visual` verifies structural fidelity (paragraphs, runs, breaks, raw OPC parts), not visual rendering.
- Visual evidence is inherited from the frozen v2.0.0 release.
- **Accurate wording:** *"v2.0 Golden structural regression PASS; visual evidence inherited from frozen v2.0 release."*

---

## 8. Summary of Deferred Acceptance

The following capabilities exist in the engine in small, correct, and well-tested forms, but their formal phase acceptance is strictly deferred:

1. **Phase 2 Deferred Acceptance:**
   - Unified CLI inspection flag (`--inspect`)
   - Complete dry-run preview formatting for user display
   - Non-zero exit code integration with legacy scripts
   - Formal zero-output proof across format suites
2. **Phase 3 Deferred Acceptance:**
   - Public CLI parameter migration (`--in-place`, `--mode`, `--json`)
   - HTTP endpoint `/clean` and `/inspect` migration to unified pipeline
   - Error code mapping to HTTP status codes
3. **Phase 10 Deferred Acceptance:**
   - Multi-format idempotence test suite (XLSX, PPTX, PDF, images, text)
   - Property-based testing (Hypothesis)
   - Chaos/fuzz testing for corrupted containers
