# ClearMark v2.1.0-RC1 — Validation Plan

## 1. Scope & Execution Principles

This document establishes the comprehensive, autonomous validation program for **ClearMark v2.1.0-RC1** prior to stable promotion.

- **Target Release**: ClearMark v2.1.0-RC1
- **Tag**: `v2.1.0-rc1` (Immutable target: `9ecfea135f7b871f226313bfc7f101d07f578d3b`)
- **Package Source Commit**: `32e1a2c3afae7d6b738630787ce4d2f7b3640c56`
- **Package Digest**: `33616f74730a0e026efa751d1fb5d86d5f310e2d66f6de3d34afec3635d716d9`
- **Repository**: `wrust0608/clearmark`
- **Underlying Principle**: Zero human manual file sourcing. Validation uses the supplied synthetic real-world corpus (`validation_input/ClearMark_RC1_Validation_Corpus_v1.zip`), installed to `.local_validation_samples/`, augmented with local project fixtures for HEIC coverage.

---

## 2. Validation Gates (V0 – V10)

| Gate | Name | Focus | Mandatory Pass Criteria |
| :--- | :--- | :--- | :--- |
| **V0** | **Freeze & Environment** | DOCX core frozen vs v2.0.0, golden/candidate fixture hashes, immutable tag target | Core diff EMPTY, fixture hashes match exact SHA256 |
| **V1** | **Artifact Identity & Clean-Room** | Independent package audit, 15 security & integrity checks | `overall_status = PASS`, `rc_ready = true` |
| **V2** | **CLI & API Acceptance** | `watermarks` CLI (`inspect`, `clean`, `verify`), stdlib HTTP service endpoints | All CLI commands exit 0; `/health`, `/capabilities`, `/inspect`, `/clean` return 200 OK |
| **V3** | **Capability Matrix** | 23 canonical format policies in `FormatPolicyRegistry` vs `/capabilities` | 23/23 policies verified with matching capabilities |
| **V4** | **Real-World Corpus** | 23 policies evaluated with representative synthetic samples | Original hashed -> inspected -> dry-run verified -> cleaned -> idempotence verified -> timing logged |
| **V5** | **Office Lossless Fidelity** | Structural invariant validators for DOCX, XLSX, PPTX, Unicode text | `fidelity_guaranteed: True`, strict OPC container preservation, zero visible text corruption |
| **V6** | **Negative / Security** | Hostile, truncated, and malformed files | Preflight fail-closed rejection before mutation, no traversal, no crash |
| **V7** | **Batch & Stress** | 100-file valid batch, mixed batch, 1–100 MiB stress files | 100% reconciliation, fault isolation, strict 32 MiB batch per-file limit enforcement |
| **V8** | **Documentation Truthfulness** | Parity between documentation, CLI help, and runtime capabilities | Zero contradictions, consistency tests pass |
| **V9** | **Soak & Stability** | Multi-cycle processing loops | Zero memory growth/leakage, identical repeated clean outputs |
| **V10** | **Final Decision** | Defect triage & promotion gating | 0 S0 (blocker), 0 S1 (major) -> `PROMOTE_TO_V2.1.0` |

---

## 3. Coverage Matrix

- **Canonical Format Policies**: 23
- **Corpus Bundled Samples**: 22 policies
- **Project Test Fixtures**: 1 policy (`.heic` via `tests/fixtures/sample_c2pa.heic`)
- **Total Validated Policies**: 23/23 (100% canonical policy coverage)
