# ClearMark v2.1.0 — Stable Release Record

## 1. Executive Summary

ClearMark v2.1.0 is the first stable production promotion of the fully validated v2.1 release line. This release promotes release candidate `v2.1.0-rc1` following comprehensive validation, soak stability verification, full CLI/HTTP contract reconciliation, and independent clean-room package auditing.

Following post-publication audit, the stable packaging artifact was updated via `DETERMINISTIC_STABLE_REPACKAGE` to normalize the internal package root to `ClearMark-v2.1.0/` (superseding the first release package which retained `ClearMark-v2.1.0-RC1/`). Production payloads remain 100% byte-identical.

| Parameter | Specification | Status |
| :--- | :--- | :---: |
| **Release** | ClearMark v2.1.0 | VERIFIED |
| **Repository** | `wrust0608/clearmark` | VERIFIED |
| **Visibility** | PRIVATE | VERIFIED |
| **Repository Type** | INDEPENDENT | VERIFIED |
| **Original Upstream** | `guillaumemeyer/watermarks-remover` | VERIFIED |
| **License** | MIT License (all notices preserved) | VERIFIED |
| **Promotion Source** | `v2.1.0-rc1` | VERIFIED |
| **RC Tag Target** | `9ecfea135f7b871f226313bfc7f101d07f578d3b` | VERIFIED |
| **Package Source Commit** | `32e1a2c3afae7d6b738630787ce4d2f7b3640c56` | VERIFIED |
| **Stable Tag** | `v2.1.0` | VERIFIED |
| **Stable Tag Target** | `7a479f97ee0f034080e93beaf74e86d526956991` | VERIFIED |
| **Validation Decision** | `PROMOTE_TO_V2.1.0` | VERIFIED |
| **Open Defects** | S0: 0, S1: 0, S2: 0, S3: 0 | VERIFIED |
| **Product Defect** | NO | VERIFIED |
| **Production Source Changed** | NO | VERIFIED |
| **Product Contract Drift** | NONE | VERIFIED |
| **Promotion Mode** | `DETERMINISTIC_STABLE_REPACKAGE` | VERIFIED |
| **Stable Artifact Revision** | CORRECTED PACKAGING LABEL | VERIFIED |
| **Stable Internal Root** | `ClearMark-v2.1.0/` | VERIFIED |
| **Original Superseded SHA256** | `33616f74730a0e026efa751d1fb5d86d5f310e2d66f6de3d34afec3635d716d9` | SUPERSEDED |
| **Current Canonical Stable SHA256** | `6e58055c49e94abe3437048d78affa53fbf0a34e5992e50621b6c50751ac79f1` | VERIFIED |
| **Stable Package Filename** | `FINAL_RELEASE_PACKAGE_v2.1.0.zip` | VERIFIED |
| **Independent Package Audit** | 15/15 gates PASS (`overall_status = PASS`, `stable_ready = true`) | VERIFIED |
| **Stable Publish Status** | PUBLISHED / VERIFIED | VERIFIED |
| **Stable Release URL** | `https://github.com/wrust0608/clearmark/releases/tag/v2.1.0` | VERIFIED |
| **Downloaded GitHub Package SHA256** | `6e58055c49e94abe3437048d78affa53fbf0a34e5992e50621b6c50751ac79f1` | VERIFIED |
| **Transport Verification** | PASS (downloaded SHA == published checksum == local stable SHA) | VERIFIED |
| **RC1 Retained** | YES (prerelease intact on GitHub) | VERIFIED |
| **RC1 Tag Unchanged** | YES (`9ecfea135f7b871f226313bfc7f101d07f578d3b`) | VERIFIED |

---

## 2. Packaging Defect Correction Details

1. **Defect**: The initial stable release ZIP was promoted via Path A (`BYTE_IDENTICAL_RC1_PROMOTION`), which preserved the inner directory root name `ClearMark-v2.1.0-RC1/`.
2. **Correction**: Built canonical stable package via Path B (`DETERMINISTIC_STABLE_REPACKAGE`) using the canonical internal root `ClearMark-v2.1.0/`.
3. **Payload Identity**:
   - Total RC1 members: 527
   - Total stable members: 527
   - Path-normalized matching members: 527
   - Byte-identical members: 525
   - Intentional metadata differences: 2 (`PACKAGE_MANIFEST.json`, `SHA256SUMS`)
   - Unexpected differences: 0
4. **Superseded Record**: Preserved permanently at `artifacts/v2.1/stable/SUPERSEDED_STABLE_ARTIFACT.json`.
5. **Release Assets**: The superseded assets on GitHub release `v2.1.0` were replaced with the corrected artifacts, and `STABLE_VS_RC1_DIFF.json` was uploaded as proof of payload identity.

---

## 3. Validation & Stabilization Invariants

1. **Validation Gates**: V0 through V10 fully executed with zero failures.
2. **Canonical Format Coverage**: All 23 format policies in `FormatPolicyRegistry` verified against real-world and synthetic corpora.
3. **Office Lossless Fidelity**:
   - DOCX: Invariant paragraphs, runs, tables, and page count preserved; core diff against `v2.0.0` is strictly EMPTY.
   - XLSX: Workbook opens cleanly in Calc without repair dialogs; formulas and shared strings intact.
   - PPTX: 3/3 slides preserved with intact geometry and theme layouts.
4. **Security & Malformed Handling**: Fail-closed preflight rejection on corrupt containers, zipbombs, and XML expansions.
5. **Soak Stability**: 10 server cycles, 10 clean sessions, 3 batch reruns, 3 UI reloads; bounded asymptotic memory plateau with active GC reclamation.
6. **Contract Disambiguation**: Top-level 256 MiB input limit, 64 MiB stdin limit, 384 MiB HTTP body limit, 32 MiB batch per-file limit, and 100/50 batch count ceilings reconciled without product drift.
