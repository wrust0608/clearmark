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
