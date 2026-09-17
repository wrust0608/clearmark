# ClearMark v2.1.0-RC1 — Manual Verification Checklist

All validation gates (V0 through V10) have been executed with automated structural and cryptographic proofs. For human operators performing manual visual spot-checks, the following 5-point checklist may be reviewed:

1. **DOCX Visual Layout**:
   - Open `artifacts/v2.1/docx_evidence/04_CANDIDATE_LOSSLESS_OUTPUT.docx` in Microsoft Word or LibreOffice Writer.
   - Confirm headings, pagination (5 manual page breaks), 1 embedded table, and visible text match `01_GOLDEN_ORIGINAL_UNTOUCHED.docx` with zero run fragmentation.
   - **Automated Structural Proof**: PASS (paragraphs: 204, runs: 288, tables: 1, breaks: 5, `visible_text_exact: True`).

2. **XLSX Calculation & Styles**:
   - Open `.local_validation_samples/spreadsheets/01_sales_dashboard_realistic.xlsx` and its cleaned output in Microsoft Excel.
   - Confirm cell formulas, conditional styling, and shared strings are intact.
   - **Automated Structural Proof**: PASS (`fidelity_guaranteed: True`, status: `NO_CHANGE_REQUIRED`).

3. **PPTX Presentation Geometry**:
   - Open `.local_validation_samples/presentations/01_product_brief_metadata_positive.pptx` in Microsoft PowerPoint.
   - Confirm slide count (3 slides), master/layout themes, and embedded shape geometries are preserved.
   - **Automated Structural Proof**: PASS (`strict_raw_opc_non_targets_identical: True`, `slide_structures_and_geometry_invariant: 3 slides checked`).

4. **Unicode & Contextual Text**:
   - Inspect `.local_validation_samples/text/01_vietnamese_unicode_metadata.txt`.
   - Confirm Vietnamese tone marks and diacritics (`Hà Nội mùa thu`) are 100% intact while invisible steganographic control characters (`0x200B`, `0xFEFF`, etc.) are stripped.
   - **Automated Structural Proof**: PASS (diacritics preserved: True).

5. **Release Package Integrity**:
   - Confirm `artifacts/v2.1/release_candidate/FINAL_REVIEW_PACKAGE_v2.1.0-RC1.zip` SHA-256 matches:
     `33616f74730a0e026efa751d1fb5d86d5f310e2d66f6de3d34afec3635d716d9`.
   - **Automated Proof**: PASS (independent audit clean-room PASS across all 15 audit gates).
