# Phase 13 Release Evidence Automation Report

**Date**: 2026-09-17  
**Branch**: `v2.1-dev`  
**Phase Status**: **PASS / COMPLETED**  
**Phase 14 Status**: **NOT STARTED**  

---

## 1. Executive Summary

Phase 13 delivers a single-command, fully automated, deterministic release evidence collection and verification engine for ClearMark v2.1.
The builder script (`tools/build_release_evidence.py`) aggregates all operational metrics, format capabilities, resource ceilings, contract invariants, git state, frozen-core integrity proofs, and test verification results directly from executable source truth into a canonical, self-verifying evidence bundle under `artifacts/v2.1/release_evidence/`.

Manual copy-paste of test counts, capability totals, resource constants, and cryptographic hashes has been completely eliminated.

---

## 2. Architecture & Source-of-Truth Hierarchy

The release evidence system strictly derives its data from primary runtime sources, rejecting secondary or stale prose:

```
                  Primary Runtime Sources
     ┌──────────────────────┬──────────────────────┐
     │                      │                      │
FormatPolicyRegistry   Production Constants   Git Repository State
 (format_policy.py)   (common, server, etc.)   (HEAD, v2.0.0 tag)
     │                      │                      │
     ▼                      ▼                      ▼
┌───────────────────────────────────────────────────────────┐
│              tools/build_release_evidence.py              │
│                                                           │
│  - Fail-closed validation gates                           │
│  - Read-only toward production inputs                     │
│  - Privacy sanitization & relative paths                  │
│  - Deterministic JSON serialization                       │
│  - Zero external network requests                         │
│  - Atomic publishing via temporary staging                │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
                artifacts/v2.1/release_evidence/
                ├── release_evidence.json
                ├── release_evidence.md
                ├── CAPABILITIES.json
                ├── LIMITS.json
                ├── PROVENANCE.json
                ├── TEST_RESULTS.json
                ├── HASHES.json
                ├── MANIFEST.json
                └── MANIFEST.sha256
```

### Hierarchy of Authority
1. **Runtime Registries & Production Modules**: `FormatPolicyRegistry`, `ExitCode`, `ErrorCode`, `SecurityLimits`, `common.MAX_INPUT_BYTES`, etc.
2. **Git Object Database**: Cryptographic commit hashes and object verification via `git cat-file -t`.
3. **Automated Test Runners**: Real test execution outputs parsed via structured regex with duration and error accounting.
4. **Historical Measured Artifacts**: `phase11_benchmark.json` and `phase11_closure_guardrails.json` (explicitly classified as `HISTORICAL_MEASURED_EVIDENCE`).
5. **Phase Documentation**: Referenced as provenance only; never parsed as primary runtime truth.

---

## 3. Schema & Generated Bundle Specification

The evidence bundle adheres to Schema Version **`1.0`**.

### Artifact Manifest

| File | Purpose | Format |
|:---|:---|:---|
| **`release_evidence.json`** | Comprehensive unified machine-readable evidence root | JSON (Schema 1.0) |
| **`release_evidence.md`** | Human-readable audit report and quality summary | GFM Markdown |
| **`CAPABILITIES.json`** | Exported policy matrix (23 policies, 37 extensions) | JSON |
| **`LIMITS.json`** | Resource and size bounding constants with scopes | JSON |
| **`PROVENANCE.json`** | Verified phase 0–13 commit provenance records | JSON |
| **`TEST_RESULTS.json`** | Automated suite execution counts, skips, durations | JSON |
| **`HASHES.json`** | SHA-256 hashes of critical repo and fixture files | JSON |
| **`MANIFEST.json`** | Cryptographic inventory of all generated bundle files | JSON |
| **`MANIFEST.sha256`** | SHA-256 signature of `MANIFEST.json` (self-hash rule) | Text / sha256sum |

---

## 4. Key Security & Quality Guarantees

### 4.1 Git Cleanliness & Release Readiness
- **Default Behavior**: Running in `--full` mode requires a 100% clean git working tree. If untracked or modified files exist, the tool halts immediately with exit code 1.
- **Diagnostic Mode**: The `--allow-dirty` flag permits diagnostic evaluation during development, but explicitly sets `release_ready = False` and `overall_status = "DIAGNOSTIC_ONLY"`.
- **Release Ready Contract**: `release_ready = True` is emitted **only** when running `--full` on a clean working tree with 100% of validation gates passing.

### 4.2 Cross-Contract Semantic Invariants
The generator asserts semantic parity between CLI, HTTP, and Security subsystems:
- Numeric limits breach $\rightarrow$ `PROCESSING_LIMIT_EXCEEDED` $\rightarrow$ CLI exit 6, HTTP 413.
- Unsupported archive features $\rightarrow$ `UNSUPPORTED_ARCHIVE_FEATURE` $\rightarrow$ CLI exit 4, HTTP 422.
- Malformed containers $\rightarrow$ `INVALID_CONTAINER` $\rightarrow$ CLI exit 4, HTTP 400.
- Fidelity / invariant failures $\rightarrow$ `VALIDATION_FAILED` $\rightarrow$ CLI exit 3, HTTP 422.
- Exit code 2 is strictly reserved for `UNSUPPORTED` format routing.
- Batch queue ceiling (100 files) and HTTP `/batch` request ceiling (50 files) are distinctly enforced.

### 4.3 Frozen Core & Fixture Hash Verification
- **Frozen DOCX Subsystem**: Automates `git diff v2.0.0 -- service/scripts/docx/` and asserts `EMPTY` (0 lines changed).
- **Cryptographic DOCX Fixtures**:
  - `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (**MATCH**)
  - `04_CANDIDATE_LOSSLESS_OUTPUT.docx`: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (**MATCH**)

### 4.4 Privacy Scrubbing & Zero Egress
- **Sanitization**: Path normalizers strip local developer paths, home directories, usernames, and machine hostnames, emitting strictly repository-relative paths with forward slashes (`/`).
- **No Document Body Leakage**: Document contents and carrier strings are excluded; reports contain only metadata.
- **Zero External Network**: 0 socket or HTTP connections to remote servers (enforced and tested via monkeypatching in `tests/test_release_evidence.py`).

### 4.5 Atomic Publication & Self-Hashing Invariant
- **Atomic Swap**: The evidence bundle is constructed in a temporary sibling directory on the same filesystem (`artifacts/v2.1/release_evidence_tmp_*`), fully validated, and swapped into place atomically. A failed run never leaves a partial or corrupt bundle.
- **Self-Hashing Rule**: `MANIFEST.json` lists SHA-256 hashes of all files in the bundle except itself; `MANIFEST.sha256` records the hash of `MANIFEST.json`.

---

## 5. Phase 12 Provenance Synchronization

Prior to Phase 13 execution, the documentation commit typo in `PHASE12_DOCUMENTATION_REPORT.md` and `ROADMAP.md` was resolved:
- **Canonical documentation implementation commit**: `c6a4b3afbc1d58e30d39202746449f089735bb3d` (verified in Git object database).
- **Typo hash**: `c6a4b3a4a98404a9e4070a2719a997ecab7289ee` removed (non-existent object).
- **Semantic truthfulness closure commit**: `02cd1e75525ca0ce238e87413a96860d5dd14d10`.

---

## 6. Verification & Automated Test Results

### 6.1 Unit Tests for Release Evidence Builder
Suite: `tests/test_release_evidence.py`
- **Tests**: 16 passed in 0.74s
- **Coverage**: Pytest output regex parsing (normal, failure, warnings, errors, xfailed), privacy scrubbing, relative path normalization, capability extraction, limit extraction against production constants, contract exit code and HTTP status mapping, cross-contract semantic assertions, frozen core diff verification, fixture hash verification, phase provenance verification, manifest validation, atomic directory publishing, subprocess timeout handling, failure excerpt capturing, zero-network enforcement.

### 6.2 Smoke & Full Integration Invocations
- **Quick Smoke**: `python tools/build_release_evidence.py --quick --allow-dirty`
  - Completed in 7.94s, status `DIAGNOSTIC_ONLY`.
- **Canonical Full Command**: `python tools/build_release_evidence.py --full`
  - Executes all 8 verification suites including canonical full pytest.

---

## 7. Production Source Changes

**NONE**. No code files in `service/` or `service/scripts/` were modified.
All additions were restricted to:
- `tools/build_release_evidence.py`
- `tests/test_release_evidence.py`
- `docs/v2.1/PHASE13_RELEASE_EVIDENCE_REPORT.md`
- `docs/v2.1/PHASE12_DOCUMENTATION_REPORT.md` (provenance typo fix)
- `docs/v2.1/ROADMAP.md` (provenance typo fix and Phase 13 update)
- `artifacts/v2.1/release_evidence/*`

---

## 8. Commit Provenance

- **Release Evidence Builder Commit**: `53e65b6f3a7eb7ec882b453e1a6beaa53a2ef565`
- **Phase 13 Evidence Closure Commit**: `e3cca1a7ad4bb1b12b23023e32bdf55959952549`

