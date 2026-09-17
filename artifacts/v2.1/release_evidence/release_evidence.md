# ClearMark v2.1 Release Evidence Report

- **Generated At (UTC)**: `2026-09-17T14:46:42Z`
- **Schema Version**: `1.0`
- **Target Release**: `v2.1.0`
- **Execution Mode**: `full`
- **Overall Evidence Status**: **`PASS`**
- **Release Ready**: **`True`**

---

## 1. Git Repository State

- **HEAD Commit**: `3d3657a783a3a511502b5bcad2dba6dd263ba504`
- **Branch**: `v2.1-dev`
- **Clean Working Tree**: `True`
- **v2.0.0 Baseline Commit**: `758d3085b8868566209a82ea981a32aa61147a44`

## 2. Frozen Core Integrity

- **DOCX Frozen Path**: `service/scripts/docx/`
- **Baseline Diff against v2.0.0**: `EMPTY`
- **Golden DOCX SHA256 Match**: `MATCH`
- **Candidate DOCX SHA256 Match**: `MATCH`

## 3. Format Capabilities Summary

- **Canonical Policies**: `23`
- **Total Registered Extensions**: `37`
- **Extension Aliases**: `14`
- **Runtime Available Policies**: `22`
- **Dependency Sensitive Policies**: `['pdf']`
- **Verify Supported Policies**: `['docx', 'pptx', 'xlsx']`

## 4. Test Verification Suites

| Suite | Passed | Skipped | Failed | Duration | Status |
|:---|:---|:---|:---|:---|:---|
| `canonical_full_pytest` | 1968 | 152 | 0 | 113.02s | **PASS** |
| `capabilities_and_api_contract` | 44 | 0 | 0 | 5.12s | **PASS** |
| `format_lossless_regressions` | 135 | 0 | 0 | 12.33s | **PASS** |
| `performance_harness` | 11 | 0 | 0 | 22.23s | **PASS** |
| `phase10_idempotence` | 139 | 0 | 0 | 6.13s | **PASS** |
| `phase12_docs_consistency` | 17 | 0 | 0 | 0.16s | **PASS** |
| `phase4_batch_contract` | 23 | 0 | 0 | 2.39s | **PASS** |
| `phase9_security` | 141 | 0 | 0 | 1.36s | **PASS** |

---

## 5. Security & Invariant Proofs

- **Zero Network Egress**: PROVEN (0 socket calls, zero egress test passed)
- **Metadata-Only Error Contract**: PROVEN (no document body leakage in reports)
- **ZipSlip & Path Traversal**: PROVEN (fail-closed across relative, Windows UNC, absolute)
- **Decompression Bomb Protection**: PROVEN (100:1 ratio, 64 MiB member, 128 MiB total bounds)
- **XML Bomb & Entity Rejection**: PROVEN (expat streaming depth <=100, elements <=500k)
- **Idempotence Fixed Point**: PROVEN ($C(C(x)) == C(x)$ byte and hash fixed point)

