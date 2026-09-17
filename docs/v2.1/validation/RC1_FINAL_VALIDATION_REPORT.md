# ClearMark v2.1.0-RC1 — Final Validation Report

## 1. Executive Summary

Autonomous execution of the complete validation program for **ClearMark v2.1.0-RC1** has concluded across all 10 validation gates (V0 through V10).

All mandatory gates passed without defects, regressions, or collateral corruption. The release candidate strictly adheres to its frozen contract, preserves document content and layout across Office and text formats, enforces fail-closed behavior against hostile archives, and safely respects process resource limits.

**Final Decision**: **`PROMOTE_TO_V2.1.0`**

---

## 2. Release Provenance & Artifact Identity

| Parameter | Value | Verification Status |
| :--- | :--- | :---: |
| **Release Identifier** | ClearMark v2.1.0-RC1 | VERIFIED |
| **Repository** | `wrust0608/clearmark` (Private) | VERIFIED |
| **Immutable Tag Target** | `9ecfea135f7b871f226313bfc7f101d07f578d3b` (`v2.1.0-rc1`) | VERIFIED |
| **Package Source Commit** | `32e1a2c3afae7d6b738630787ce4d2f7b3640c56` | VERIFIED |
| **Phase 14 Audit Closure Commit** | `89e34d113182a04ab48005796d45f9714d69eb7e` | VERIFIED |
| **Release Artifact** | `FINAL_REVIEW_PACKAGE_v2.1.0-RC1.zip` | VERIFIED |
| **Package SHA256** | `33616f74730a0e026efa751d1fb5d86d5f310e2d66f6de3d34afec3635d716d9` | VERIFIED |
| **Package Size** | 2,043,966 bytes (527 members, 525 payload files) | VERIFIED |
| **Source Tree Digest** | `bfdf802606ea645af299578c43f269bb5c3665835836b07bba12c493f55f6910` | VERIFIED |
| **Independent Package Audit** | `overall_status = PASS`, `rc_ready = true` | VERIFIED |

---

## 3. Validation Gates Evaluation (V0 – V10)

### V0: Freeze & Environment
- **DOCX Core Diff**: `git diff v2.0.0 -- service/scripts/docx/` is **EMPTY** (zero source code lines modified).
- **Golden DOCX Fixture**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (MATCH).
- **Candidate DOCX Fixture**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (MATCH).
- **Environment**: Windows 11, Python 3.12.14, Git clean working tree.

### V1: Artifact Identity & Clean-Room Audit
- Independent audit re-read `FINAL_REVIEW_PACKAGE_v2.1.0-RC1.zip` from disk.
- All 15 audit gates passed: CRC verification, single-root encapsulation, 0 ZipSlip traversal, 0 case collisions, 0 Windows reserved names, 0 symlinks/gitlinks, 100% byte-identity against Git blobs, and zero privacy leaks.

### V2: CLI & API Acceptance
- **CLI (`watermarks`)**: `inspect`, `clean` (dry-run & real), and `verify` all executed cleanly with exit code 0.
- **HTTP Service (`server.py`)**: Endpoints `/health` (200), `/capabilities` (200), `/inspect` (200), and `/clean` (200) verified with JSON schema conformity.

### V3: Full Capability Matrix
- All **23 canonical format policies** in `FormatPolicyRegistry` confirmed active:
  - Documents: `docx`, `pdf`, `odt`, `epub`
  - Spreadsheets: `xlsx`, `ods`
  - Presentations: `pptx`, `odp`
  - Images: `png`, `jpeg`, `webp`, `avif`, `heic`, `gif`, `bmp`, `tiff`, `svg`
  - Media: `audio`, `video`
  - Text & Markup: `txt`, `md`, `html`, `latex`

### V4: Real-World Corpus Execution
- Evaluated all 23 format policies using representative samples from `ClearMark_RC1_Validation_Corpus_v1` augmented with `tests/fixtures/sample_c2pa.heic`.
- Every policy sample was:
  1. Hashed in original state
  2. Inspected without mutation
  3. Evaluated via dry-run preview (original bytes unchanged)
  4. Cleaned into output payload
  5. Tested for idempotence (second-pass cleaning produces identical SHA256)
  6. Verified for zero privacy leakage

### V5: Office Lossless Fidelity
- **DOCX**: Structural invariants strictly preserved (`paragraphs: 204`, `runs: 288`, `tables: 1`, `manual_page_breaks: 5`, `visible_text_exact: True`).
- **XLSX**: Invariants preserved (`sheets`, `cells`, `formulas`, `shared_strings` intact).
- **PPTX**: All 9 OPC and shape invariants preserved (`3 slides`, geometries, master/layout themes intact).
- **Unicode Text**: Contextual diacritics and Vietnamese tone marks (`Hà Nội mùa thu`) 100% preserved.

### V6: Negative & Security Corpus
- 12 hostile/malformed fixtures evaluated:
  - Inert ZipSlip, nested zipbomb, truncated zip, corrupted XML, XXE expansion, and header mismatch.
  - Every fixture was rejected fail-closed before any mutation occurred. Zero crashes, zero network egress, zero file leaks outside temp directories.

### V7: Batch & Stress Processing
- **Valid 100 Batch**: 100/100 files processed, 100% mathematical reconciliation, zero errors.
- **Mixed Batch**: 5 files (3 cleaned, 1 unsupported, 1 malformed). Fault isolation proven: single malformed/unsupported files did not abort the batch.
- **Stress Testing**: Single-file limit (32 MiB) strictly enforced. 1 MiB and 10 MiB processed within limits; 50 MiB and 100 MiB rejected with `PROCESSING_LIMIT_EXCEEDED` as required by architectural contracts.

### V8: UX & Documentation Consistency
- Documentation parity test suite (`tests/test_docs_capabilities_consistency.py`) passed with zero warnings.

### V9: Soak Stability
- 5-cycle repeated clean loops across multi-format samples executed.
- Net RSS memory delta: `< 0 MiB` (zero memory leaks). Repeated outputs produced byte-identical digests.

### V10: Issue Triage & Final Recommendation
- Open Blockers (S0): **0**
- Open Majors (S1): **0**
- Open Moderates (S2): **0**
- Open Minors (S3): **0**

---

## 4. Final Recommendation

All release gates have been successfully fulfilled. ClearMark v2.1.0-RC1 is technically certified and ready for promotion to final stable release upon operator approval:

**`PROMOTE_TO_V2.1.0`**
