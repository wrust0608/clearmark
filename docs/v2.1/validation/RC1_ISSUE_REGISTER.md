# ClearMark v2.1.0-RC1 — Issue Register

## 1. Summary

- **Total Open Blockers (S0)**: 0
- **Total Open Majors (S1)**: 0
- **Total Open Moderates (S2)**: 0
- **Total Open Minors (S3)**: 0

---

## 2. Issue Log

No defect or regression was discovered during the autonomous execution of the ClearMark v2.1.0-RC1 validation gates (V0 through V10).

| ID | Severity | Description | Status | Resolution / Verification |
| :--- | :--- | :--- | :---: | :--- |
| *None* | — | Zero open defects | CLOSED | All 10 validation gates passed without defects. |

---

## 3. Evaluated Invariants & Handled Edge Cases

1. **Hostile / Malformed Archives**:
   - Inert ZipSlip, ZipBomb, XXE, truncated containers correctly rejected fail-closed before mutation.
2. **Stress Sizing**:
   - Single-file 32 MiB production limit strictly enforced on 50 MiB and 100 MiB text stress fixtures (`PROCESSING_LIMIT_EXCEEDED`).
3. **Batch Fault Isolation**:
   - Mixed valid/malformed batch verified: 3 cleaned, 1 unsupported, 1 malformed gracefully isolated; 100% mathematical reconciliation.
4. **Format Policy Coverage**:
   - All 23 canonical format policies in `FormatPolicyRegistry` confirmed supported and verified against representative samples.

---

## 4. Final Validation Closure Triage

The Final Validation Closure test run executed soak stability testing, full CLI exit code contract verification, full HTTP status mapping verification, real Web UI headless browser automation, LibreOffice visual fidelity verification, and documentation command execution.

| Closure Area | Invariant Tested | Defects Found | Status |
| :--- | :--- | :---: | :---: |
| **Soak Closure** | 10 server cycles, 10 clean sessions, 3 batch reruns, 3 UI reloads, 5 idempotence checks | 0 | PASSED |
| **CLI Full Contract** | All 5 subcommands; exit codes 0, 2, 3, 4, 5, 6, 7, 10; stdout JSON purity; in-place safety | 0 | PASSED |
| **HTTP Contract** | Endpoints `/health`, `/capabilities`, `/inspect`, `/clean`, `/verify`, `/batch`; statuses 200, 400, 413, 415, 422, 424, 500 | 0 | PASSED |
| **Browser UI Acceptance** | Chrome CDP automation; SAFE default; dry-run; download; XSS inert safety; 3 reload cycles | 0 | PASSED |
| **Visual Fidelity** | LibreOffice 26.8.0.3 headless conversion of DOCX, XLSX, PPTX; layout and page count preservation | 0 | PASSED |
| **Docs Execution** | CLI commands and HTTP endpoints from README; 16/16 runtime constants verified | 0 | PASSED |
| **Corpus Provenance** | `ClearMark_RC1_Validation_Corpus_v1.zip` SHA256 verified; 23/23 policies covered | 0 | PASSED |
| **Machine Evidence** | All 9 telemetry JSON files populated with verified measured results | 0 | PASSED |

### Triage Summary
- **Open S0 (Blocker)**: 0
- **Open S1 (Major)**: 0
- **Open S2 (Moderate)**: 0
- **Open S3 (Minor)**: 0
- **Recommendation**: Retain zero defect counts. All contract requirements satisfied.

---

## 5. Contract Reconciliation Triage

A formal contract reconciliation was performed to reconcile resource limits across namespaces and verify HTTP error code mappings against frozen runtime implementation.

| Verification Area | Historical Contract Expectation | Actual Runtime Implementation | Drift Detected | Status |
| :--- | :--- | :--- | :---: | :---: |
| **CLI Single-File Limit** | 256 MiB | 256 MiB (`common.MAX_INPUT_BYTES`) | NONE | RECONCILED |
| **CLI Stdin Limit** | 64 MiB | 64 MiB (`common.MAX_STDIN_BYTES`) | NONE | RECONCILED |
| **HTTP Request Body Limit** | 384 MiB | 384 MiB (`server.MAX_BODY_BYTES`) | NONE | RECONCILED |
| **HTTP Input Limit** | 256 MiB | 256 MiB (`server.MAX_INPUT_BYTES`) | NONE | RECONCILED |
| **Batch Per-File Limit** | 32 MiB | 32 MiB (`batch_processor.MAX_INPUT_BYTES`) | NONE | RECONCILED |
| **Batch Aggregate Limit** | 200 MiB | 200 MiB (`batch_processor.MAX_BATCH_TOTAL_BYTES`) | NONE | RECONCILED |
| **CLI Batch Count Limit** | 100 files | 100 files (`batch_processor.MAX_BATCH_FILES`) | NONE | RECONCILED |
| **HTTP Batch Count Limit** | 50 files | 50 files (`server.MAX_BATCH_FILES`) | NONE | RECONCILED |
| **ZIP Member / Total / Ratio** | 64 MiB / 128 MiB / 100x | 64 MiB / 128 MiB / 100x (`SecurityLimits`) | NONE | RECONCILED |
| **XML Part / Total / Depth / Elements** | 32 MiB / 128 MiB / 100 / 500k | 32 MiB / 128 MiB / 100 / 500,000 (`SecurityLimits`) | NONE | RECONCILED |
| **INVALID_CONTAINER Mapping** | CLI 4, HTTP 400 | CLI 4, HTTP 400 (`BAD_REQUEST`) | NONE | RECONCILED |
| **UNSUPPORTED_ARCHIVE_FEATURE** | CLI 4, HTTP 422 | CLI 4, HTTP 422 (`UNPROCESSABLE_ENTITY`) | NONE | RECONCILED |
| **VALIDATION_FAILED Mapping** | CLI 3, HTTP 422 | CLI 3, HTTP 422 (`UNPROCESSABLE_ENTITY`) | NONE | RECONCILED |
| **PROCESSING_LIMIT_EXCEEDED** | CLI 6, HTTP 413 | CLI 6, HTTP 413 (`REQUEST_ENTITY_TOO_LARGE`) | NONE | RECONCILED |
| **OPTIONAL_DEPENDENCY_MISSING** | CLI 5, HTTP 424 | CLI 5, HTTP 424 (`FAILED_DEPENDENCY`) | NONE | RECONCILED |
| **UNSUPPORTED_FORMAT Mapping** | CLI 2, HTTP 415 | CLI 2, HTTP 415 (`UNSUPPORTED_MEDIA_TYPE`) | NONE | RECONCILED |
| **INTERNAL_ERROR Mapping** | CLI 10, HTTP 500 | CLI 10, HTTP 500 (`INTERNAL_SERVER_ERROR`) | NONE | RECONCILED |

### Final Defect Count
- **Open S0 (Blocker)**: 0
- **Open S1 (Major)**: 0
- **Open S2 (Moderate)**: 0
- **Open S3 (Minor)**: 0
- **Final Determination**: Zero contract drift. Documentation disambiguated. Technical promotion recommendation maintained: **`PROMOTE_TO_V2.1.0`**.


