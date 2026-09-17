# ClearMark v2.1.0-RC1 — Release Handoff Record

| Field | Value |
| :--- | :--- |
| **Release Candidate** | ClearMark v2.1.0-RC1 |
| **Release-Engineering HEAD at handoff preparation** | `6868391270d0dc0981363ae379851be63126c719` |
| **Release-Engineering Tag Target** | Tag `v2.1.0-rc1` (resolves to finalized release commit) |
| **Source Commit** | `32e1a2c3afae7d6b738630787ce4d2f7b3640c56` |
| **Phase 14 Full Audit Closure Hash** | `89e34d113182a04ab48005796d45f9714d69eb7e` |
| **Package Filename** | `FINAL_REVIEW_PACKAGE_v2.1.0-RC1.zip` |
| **Package SHA256** | `33616f74730a0e026efa751d1fb5d86d5f310e2d66f6de3d34afec3635d716d9` |
| **Source Tree Digest** | `bfdf802606ea645af299578c43f269bb5c3665835836b07bba12c493f55f6910` |
| **Payload / Member Counts** | 525 payload files / 527 ZIP members |
| **Payload / ZIP Bytes** | 4,979,482 payload bytes / 2,043,966 ZIP bytes |
| **Canonical Pytest** | 1990 passed, 152 skipped, 0 failed, 0 warnings (124.99s) |
| **rc_ready** | `true` |
| **READY_TO_TAG** | `true` |
| **Remote Publish Status** | AUTHORIZED / IN PROGRESS |

---

## Provenance & Integrity Summary

1. **Source Integrity**:
   - Primary package source is strictly bound to commit `32e1a2c3afae7d6b738630787ce4d2f7b3640c56` via Git tree/blob objects.
   - Embedded Phase 13 evidence validates `overall_status = PASS` and `release_ready = true`.

2. **Frozen DOCX Core**:
   - `service/scripts/docx/` remains 100% byte-identical to `v2.0.0` (zero diff lines).
   - Golden fixture SHA256: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (MATCH).
   - Candidate fixture SHA256: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (MATCH).

3. **Deterministic Package Verification**:
   - Canonical artifact: `artifacts/v2.1/release_candidate/FINAL_REVIEW_PACKAGE_v2.1.0-RC1.zip`.
   - Independent audit (`tools/build_review_package.py --audit`) passes all 15 audit gates.
   - SHA256 match verified against `FINAL_REVIEW_PACKAGE_v2.1.0-RC1.zip.sha256`.

4. **Tag & Publish Status**:
   - Annotated tag `v2.1.0-rc1` prepared and authorized.
   - Remote publish to GitHub Releases authorized.
