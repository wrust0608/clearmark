# Phase 4 Batch Contract Closure Report

> **Historical Implementation Commit**: `085176ace00a776b91ece01621c23b15195e0418` (`feat(batch): complete Phase 4 isolated batch processing engine`)  
> **Production Filesystem Fix Commit (Commit A)**: `dfa948da73f5e000eb564f35415968242e338845` (`fix(batch): enforce Phase 4 batch contract invariants`)  
> **Canonical Evidence & Documentation Closure Commit (Commit C)**: `1fb5cba5ef243021bf53ef4f1498aedf76ccfa16` (`test(batch): finalize pre-Phase12 public contract`, amended from historical pre-amend commit `3370fcc7b0ef0002c30748d410293e32cd790dd0`)  
> **Gate Status**: **APPROVED / PASS**  
> **Canonical Golden DOCX SHA256**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (VERIFIED)  
> **Canonical Candidate DOCX SHA256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (VERIFIED)  
> **Frozen Core Diff**: `git diff v2.0.0 -- service/scripts/docx/` **EMPTY** (0 lines modified)

---

## 1. Executive Summary

This report documents the final closure of the historical Phase 4 batch-contract evidence debt prior to Phase 12. A comprehensive audit of `service/scripts/batch_processor.py`, `service/scripts/cli.py`, `service/scripts/server.py`, and existing batch tests was conducted to verify three critical invariants:

1. **Stable Batch Exit/Status Contract**: Preserving the frozen Phase 3 public CLI exit codes (`0` = success, `2` = unsupported, `3` = validation failed, `4` = invalid/malformed, `5` = dependency missing, `6` = limit exceeded, `10` = internal) without repurposing `2` for partial batch failure, zero inputs, or resource limits. Batch exit semantics are explicitly defined and enforced:
   - `0` = `SUCCESS` (100% of discovered items succeeded / cleaned or no change required).
   - `2` = `UNSUPPORTED` (all discovered items unsupported format; code 2 strictly retains the `UNSUPPORTED` family semantics and is never used for limits, setup, or partial failure).
   - `3` = `VALIDATION_FAILED` (homogeneous validation failures across batch).
   - `4` = `INVALID_INPUT` (malformed arguments, invalid mode, Policy B identical directory configuration, or zero inputs discovered).
   - `5` = `DEPENDENCY_MISSING` (homogeneous missing dependency across batch).
   - `6` = `LIMIT_EXCEEDED` (batch `MAX_FILES`, batch `MAX_TOTAL_BYTES`, or homogeneous item limit exceeded).
   - `7` = `BATCH_PARTIAL_FAILURE` (additive Phase 4 code for mixed outcomes; `BATCH_PARTIAL_SUCCESS` retained as alias).
   - `10` = `INTERNAL_ERROR` (unhandled internal exception).
2. **Batch Dry-Run Zero-Write Contract**: In dry-run mode (`--dry-run`), zero persistent writes occur across the filesystem. Specifically, nonexistent `--output-dir` and `--reports-dir` are never created, no per-file JSON reports or `batch_report.json` are written to disk, and input files remain byte-for-byte and timestamp immutable (`sha256`, `size`, `mtime_ns`).
3. **Recursive Directory Self-Ingestion Prevention**: In recursive directory batches (`-r`), generated outputs and reports (including nested `input_root/generated/output` and `input_root/generated/reports`) are deterministically excluded from input discovery. Re-running the exact same batch command on a live tree never ingests previously generated `.cleaned.*` files or reports, preventing multiplicative artifact growth. Explicit Policy B rejection is enforced: configuring `--output-dir` or `--reports-dir` identical to the input root raises a configuration error and exits with code `4` (`INVALID_INPUT`).

Two production defect areas were remediated in Commit A (`dfa948da73f5e000eb564f35415968242e338845` - filesystem invariants) and Commit B (`2e1fa3b3161626b6cae7d2a143311fa1b480d7ac` - canonical exit namespace). Permanent executable evidence is captured in `tests/test_batch_contract_closure.py` (23 passed).

---

## 2. Audit Findings & Production Defects Remediated

### Defect 1: Dry-Run Directory Creation & Report Persistence
- **Root Cause**: In `service/scripts/batch_processor.py`, `os.makedirs(out_dir_path, exist_ok=True)` and `os.makedirs(rep_dir_path, exist_ok=True)` were executed unconditionally before the processing loop, creating directories on disk even when `dry_run=True`. Additionally, per-file JSON reports (`{idx:04d}-{stem}.json`) and aggregate `batch_report.json` were written to `rep_dir_path` without checking `not dry_run`.
- **Fix**: Guarded `os.makedirs` and report writing calls with `if not dry_run`. In dry-run mode, nonexistent directories remain nonexistent, zero files are written to disk, and structured results are returned purely in-memory and emitted as stdout JSON.

### Defect 2: Directory Discovery Self-Ingestion & Live Tree Rerun Leak
- **Root Cause**: `discover_input_files()` lacked awareness of `output_dir` and `reports_dir`. When output or reports were nested inside the input root (`input_root/generated/output`), subsequent runs (or live scans) traversed those directories, discovering generated `.cleaned.*` artifacts and reports as new inputs. Furthermore, configuring `--output-dir == input_root` or `--reports-dir == input_root` was not guarded.
- **Fix**:
  1. Enforced **Policy B** in `process_paths`: if `out_dir_path` or `rep_dir_path` resolves to the identical canonical path as any input directory (`os.path.normcase`), raise `ValueError` ("Output directory cannot be identical to input directory..."), which CLI maps to ExitCode `4` (`INVALID_INPUT`).
  2. Implemented `_is_subpath_or_equal(child, parent)` using `os.path.normcase` and trailing separator guards for cross-platform and Windows path canonicalization.
  3. Passed `exclude_dirs=[out_dir_path, rep_dir_path]` to `discover_input_files()`. During recursive `os.walk`, subdirectories matching excluded paths or symlinks/junctions are pruned in-place (`dirs[:] = [...]`), preventing directory descent.
  4. Added `_is_link_or_junction()` to reject following symbolic links, junctions, and reparse points during discovery and per-item inspection.

### Defect 3: Batch Exit Namespace Consistency & Resource Limit Mapping
- **Root Cause**: In `service/scripts/cli.py`, `BatchLimitExceededError` was previously unhandled separately from general errors and previously documented/mapped inconsistently. Additionally, empty batches previously lacked an explicit status check, and partial failure lacked a dedicated non-colliding exit code.
- **Fix**:
  1. Preserved Phase 3 exit code semantics: `ExitCode.UNSUPPORTED` (2) strictly retains the unsupported format family semantics and is never used for limits, setup errors, or partial failures.
  2. Explicitly mapped `BatchLimitExceededError` (`MAX_FILES`, `MAX_TOTAL_BYTES`) to `ExitCode.LIMIT_EXCEEDED` (6).
  3. Mapped zero inputs discovered to `ExitCode.INVALID_INPUT` (4) with structured `error_code="NO_INPUTS"`.
  4. Introduced additive non-colliding `ExitCode.BATCH_PARTIAL_FAILURE` (7) for mixed batch outcomes, preserving `BATCH_PARTIAL_SUCCESS = 7` as alias.
  5. Implemented homogeneous all-failure propagation for batches where all items fail with the same canonical failure category.

---

## 3. Authoritative Public Exit Contract Specification

### CLI Exit Codes

| Exit Code | Identifier | Scope | Semantics |
|---|---|---|---|
| **0** | `SUCCESS` | CLI / Batch | Single file: cleaned / no change / inspected.<br>Batch: 100% of discovered items succeeded (cleaned, no change, or inspected). |
| **2** | `UNSUPPORTED` | CLI / Batch | Single file: unsupported format/capability.<br>Batch: 100% of discovered items unsupported format. **Never repurposed for limits, setup, zero inputs, or partial failure.** |
| **3** | `VALIDATION_FAILED` | CLI / Batch | Single file: output validation check failed post-clean (structural/fidelity loss).<br>Batch: 100% of items failed validation. |
| **4** | `INVALID_INPUT` | CLI / Batch | Malformed arguments, invalid mode string, unresolvable syntax, Policy B identical directory rejection, or zero inputs discovered (`NO_INPUTS`). |
| **5** | `DEPENDENCY_MISSING` | CLI / Batch | Required external dependency unavailable (e.g. PyMuPDF for PDF).<br>Batch: 100% of items failed due to missing dependency. |
| **6** | `LIMIT_EXCEEDED` | CLI / Batch | Single file: processing/resource limit exceeded.<br>Batch: batch `MAX_FILES` exceeded, batch `MAX_TOTAL_BYTES` exceeded, or 100% of items failed due to processing limit. |
| **7** | `BATCH_PARTIAL_FAILURE` | Batch | Aggregate batch completed, but at least 1 item failed (mixed cleaned, corrupt, unsupported, or error). Aliased to `BATCH_PARTIAL_SUCCESS`. |
| **10** | `INTERNAL_ERROR` | CLI / Batch | Unhandled internal exception during execution or batch setup. |

### Aggregate Batch Result Decision Table

| Batch Scenario | Aggregate State | CLI Exit Code | Rationale |
|---|---|---|---|
| All items cleaned / no change / inspected | `total == cleaned + no_change + inspected` | **0** (`SUCCESS`) | Full batch success |
| Zero input files found/discovered | `total == 0` | **4** (`INVALID_INPUT`) | Explicit `NO_INPUTS` policy; exit 2 strictly forbidden |
| Invalid configuration / syntax / Policy B | Setup error (`ValueError`, `FileNotFoundError`) | **4** (`INVALID_INPUT`) | User configuration error |
| Batch `MAX_FILES` exceeded | `BatchLimitExceededError` | **6** (`LIMIT_EXCEEDED`) | Batch ceiling resource limit |
| Batch `MAX_TOTAL_BYTES` exceeded | `BatchLimitExceededError` | **6** (`LIMIT_EXCEEDED`) | Batch ceiling resource limit |
| Internal setup exception | Unhandled `Exception` | **10** (`INTERNAL_ERROR`) | Unexpected internal failure |
| All items unsupported | `total == unsupported` | **2** (`UNSUPPORTED`) | Homogeneous unsupported family |
| Mixed success + unsupported | Partial batch | **7** (`BATCH_PARTIAL_FAILURE`) | Additive partial code; items retain `UNSUPPORTED_FORMAT` |
| Mixed success + malformed | Partial batch | **7** (`BATCH_PARTIAL_FAILURE`) | Additive partial code; items retain `INVALID_CONTAINER` |
| Mixed success + dependency missing | Partial batch | **7** (`BATCH_PARTIAL_FAILURE`) | Additive partial code; items retain `OPTIONAL_DEPENDENCY_MISSING` |
| Mixed success + limit exceeded | Partial batch | **7** (`BATCH_PARTIAL_FAILURE`) | Additive partial code; items retain `PROCESSING_LIMIT_EXCEEDED` |
| Homogeneous all validation failed | `total == validation_failed` | **3** (`VALIDATION_FAILED`) | Canonical category propagation |
| Homogeneous all single-file limits | `total == errors` (all limit) | **6** (`LIMIT_EXCEEDED`) | Canonical category propagation |
| Homogeneous all dependency missing | `total == errors` (all missing dep) | **5** (`DEPENDENCY_MISSING`) | Canonical category propagation |
| Homogeneous all malformed/invalid | `total == errors` (all container error) | **4** (`INVALID_INPUT`) | Canonical category propagation |

---

## 4. Invariant Verification Details

### A. Dry-Run Zero-Write Proof
- **Test**: `test_batch_dry_run_zero_write_contract`
- **Execution**: Target paths `<tmp>/generated/output` and `<tmp>/generated/reports` configured before invocation.
- **Assertion**: Both directories verified `exists() == False`. Zero files, zero directories, zero temp files.

### B. Input Tree Immutability
- **Test**: `test_batch_dry_run_input_tree_immutability`
- **Execution**: Snapshotted relative paths, SHA256 digests, file sizes, and nanosecond mtimes (`st_mtime_ns`) of all input files.
- **Assertion**: Post-run snapshot verified 100% identical.

### C. Recursive Directory Exclusion & Rerun Stability
- **Test**: `test_batch_recursive_nested_output_and_reports_exclusion`
- **Execution**: Recursive batch run targeting `input_root` with nested outputs at `input_root/generated/output` and reports at `input_root/generated/reports`. Ran command once, confirmed outputs created. Immediately re-ran the exact same command on the live tree.
- **Assertion**: Run 1 input count = 1. Run 2 input count = 1. No `.cleaned.*` outputs or `.json` reports ingested as source inputs. Zero multiplicative artifact growth (`file.cleaned.cleaned.docx`).

### D. Policy B: Output/Reports Dir Equals Input Dir
- **Tests**: `test_batch_output_dir_equals_input_dir_rejected`, `test_batch_reports_dir_equals_input_dir_rejected`
- **Assertion**: Setting `--output-dir <input>` or `--reports-dir <input>` raises `ValueError`, returning ExitCode `4` (`INVALID_INPUT`) with structured error JSON on `--json`.

### E. Symlink and Junction Safety
- **Test**: `test_batch_symlink_directory_safety`
- **Execution**: Created recursive directory symlink pointing back to source root.
- **Assertion**: Traversal ignored the symlink; original file processed exactly once; zero infinite loops.

### F. Windows Path Normalization
- **Test**: `test_batch_windows_case_insensitive_path_exclusion`
- **Assertion**: Subpath exclusion evaluated under mixed-case spellings (`MyWorkspace/Generated/OutPut` vs `myworkspace/generated/output`). Exclusion succeeded via `os.path.normcase`.

### G. Fault Isolation & Summary Reconciliation
- **Test**: `test_batch_fault_isolation_and_reconciliation`
- **Execution**: Batch containing 1 valid DOCX, 1 corrupt DOCX, 1 unsupported `.bin`, and 1 clean `.txt`.
- **Assertion**: `summary.reconcile()` is True; `total (4) == cleaned (1) + no_change (1) + unsupported (1) + errors (1)`. One bad file never aborts siblings.

### H. JSON Stdout Purity & Privacy
- **Tests**: `test_batch_json_stdout_purity_success_and_failure`, `test_batch_report_privacy_sentinel_absent`
- **Assertion**: `stdout` contains 100% pure JSON parsable without truncation or warning lines. Body sentinel `CONFIDENTIAL_SENTINEL_TOKEN_XYZ_987654` absent from stdout JSON, stderr, per-file reports, and batch report.

### I. Zero Network Socket Egress
- **Test**: `test_batch_zero_network_egress`
- **Assertion**: `socket.socket` and `socket.create_connection` monkeypatched to raise `AssertionError`. Batch ran with 0 network calls.

---

## 5. Verification & Regression Matrix

| Suite | Scope | Baseline | Post-Closure Result | Status |
|---|---|---|---|---|
| **Focused Closure** | `tests/test_batch_contract_closure.py` | New (23 tests) | **23 passed in 2.36s** | **PASS** |
| **Existing Batch Suites** | `test_batch_processor.py`, `test_batch_cli.py`, `test_batch_api.py` | 32 tests | **32 passed in 5.94s** | **PASS** |
| **Phase 9 Security** | `tests/test_malformed_archives.py` | 141 tests | **141 passed in 1.50s** | **PASS** |
| **Phase 10 Idempotence** | `tests/test_idempotence.py`, `tests/test_property_unicode.py` | 139 tests | **139 passed in 6.63s** | **PASS** |
| **Format Regression** | `tests/test_docx_body_carriers.py`, `tests/test_xlsx_lossless.py`, `tests/test_pptx_lossless.py` | 135 tests | **135 passed in 16.57s** | **PASS** |
| **Existing Contracts** | 8 contract test modules | 88 tests | **88 passed in 8.35s** | **PASS** |
| **Performance Harness** | `tests/test_performance_harness.py` | 11 tests | **11 passed in 39.85s** | **PASS** |
| **Canonical Full Regression** | Full repository test suite | 1912 passed, 152 skipped | **1935 passed, 152 skipped in 123.70s** | **PASS** |
| **DOCX Frozen Core Diff** | `git diff v2.0.0 -- service/scripts/docx/` | EMPTY | **EMPTY (0 lines)** | **PASS** |
| **Golden DOCX SHA256** | `01_GOLDEN_ORIGINAL_UNTOUCHED.docx` | `c05ca5c1...` | **MATCH (`c05ca5c1...`)** | **PASS** |
| **Candidate DOCX SHA256** | Pipeline cleaned output | `7aa5549f...` | **MATCH (`7aa5549f...`)** | **PASS** |
