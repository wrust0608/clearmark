# ClearMark v2.2 RC2 Hardening Report

## 1. Executive Summary

- **Repository**: `wrust0608/clearmark`
- **Branch**: `feature/v2.2.0-rc2-hardening`
- **Starting SHA (Round 1 `start_sha`)**: `add1a5a9a06e85a00dfb77e102e68877ab914df2`
- **Round 2 Starting SHA**: `d8bb90073ece32b00a0761020f21dd32c5ad54c4`
- **Corrective Code Ending SHA (`code_end_sha`)**: `621636a28cb52289e28cc19d38203c2b2d7bf2c4`
- **Report Source SHA (`report_source_sha`)**: `621636a28cb52289e28cc19d38203c2b2d7bf2c4`
- **Upstream Audited SHA**: `e4d2bd49c4cb84c5fddb50f5361618cfb3b75def` (`guillaumemeyer/watermarks-remover/main`)
- **Independent Review State**: **P0_INDEPENDENT_REVIEW_ROUND_2 COMPLETE**
- **RC2_GATE**: **PASS (Awaiting Independent Review Round 2 Verification)**
- **Full Test Suite Results**: 2076 passed, 152 skipped, 0 failed, 0 errors in 245.69s
- **Real Browser Gate (Chrome/153.0.8010.48)**: 25/25 scenario steps passed
- **Issues Matrix Overview**:
  - **Severity S1**: 6 (A01, A02, A03, A04, A05, A06) — ALL RESOLVED
  - **Severity S2**: 11 (A07, A08, A09, A10, A11, A12, A13, A14, A15, A16, A17) — ALL RESOLVED (A09/A10 classified as MITIGATED / FIDELITY-SAFE)
  - **Severity S3**: 1 (A18) — RESOLVED
- **Closure Statistics**:
  - **Fixed**: 16
  - **Mitigated / Fidelity-Safe**: 2 (A09, A10)
  - **Deferred**: 0
  - **Unresolved Blockers**: 0

---

## 2. Review & Hardening Chronology

This audit report preserves the complete progression across all review rounds:

### Round 0 — Initial Antigravity Claim
At commit `e54efe490f1e6a26acf3e0fef4c29e56a9e4259e`, Antigravity claimed `RC2_GATE=PASS`.

### Round 1 — Independent Review Findings
Independent review **REJECTED** the initial claim, finding multiple false-completion gaps:
- **A06 (FAIL)**: Dual cleaner still existed; `/clean` returned legacy output rather than canonical `Pipeline.clean()`.
- **A08 (FAIL)**: `/clean/batch` bypassed canonical `Pipeline`.
- **A07 (PARTIAL/FAIL)**: Normal clean required Layer B rewrite backend or threw ValueError instead of running safe Layer A text cleaning offline.
- **A11 (FAIL)**: Bit 3 / data-descriptor handling lacked real bit-3 archives and Central Directory parsing for PPTX raw records.
- **A17 (FAIL)**: XLSX had `text_muts_by_orig` fallback; PPTX lacked strict plan-to-patcher reconciliation and duplicate text witnesses.
- **A13 (PARTIAL)**: Surface reporting lacked honest distinction between checked field results and uninspected instructions/deletions.
- **A18 (FAIL)**: Web UI retained hardcoded v2.1 claims and absolute fidelity statements ("Bảo toàn Lossless", "Lossless 100% trung thực").
- **A02 (PARTIAL)**: `DocxMutationPlan` was mutable even after `freeze()`.
- **A09 / A10**: Inaccurately claimed as fully FIXED despite remaining architectural edge cases in Word dynamic evaluation.

### Round 1 — Corrective Implementation
Commits `eea3e0e`, `68c690a`, `296dd35`, and `b66babf` implemented:
- Strict canonical pipeline routing in `/clean` and `/clean/batch`.
- Layer A safe default for text cleaning (zero network, zero LLM).
- Real bit-3 ZIP data-descriptor handling and PPTX Central Directory raw parsing.
- Exact mutation identity enforcement for XLSX and PPTX (fail closed on unresolvable mutations).
- Full immutability for `DocxMutationPlan` via `types.MappingProxyType` and attribute mutation guards.
- Honest reclassification of A09 and A10 to `MITIGATED / FIDELITY-SAFE`.
- Removal of hardcoded v2.1 claims in Web UI and dynamic capabilities loading.
- 11 review witness tests in `tests/test_p0_review_corrections.py`.

### Round 2 — Independent Review Findings
Remote HEAD verified at `d8bb90073ece32b00a0761020f21dd32c5ad54c4`. Independent Review Round 2 identified remaining false-completion gaps:
1. **A02 (PARTIAL)**: `DocxPatcher._patch_text_part` still retained legacy fallback accepting `set[int]` / `frozenset[int]` which globally stripped matching codepoints across the XML part.
2. **A08 (FAIL)**: `/clean/batch` did not have semantic parity with `/clean` and `/batch`: top-level `mode` was ignored (falling back to SAFE), top-level `dry_run` was ignored, top-level `options` were ignored, invalid mode did not reject with 400, and `BatchProcessor` size caps (50 files, 32 MiB per-file, 200 MiB aggregate) were bypassed.
3. **UI/API Bug**: `service/web/app.js` sent `{ layer_a_only: true }` for non-DOCX single cleans, which was rejected by `server.py` with HTTP 400 Bad Request because `layer_a_only` was not in `ALLOWED_CLEAN_OPTIONS`.
4. **A07 (PARTIAL)**: `_parse_clean_options` accepted `"strategy"` and silently ignored it rather than explicitly rejecting Layer B rewrite requests until P1.
5. **A11 (PARTIAL)**: Modified OOXML entries stripped safe compatible ZIP extra fields (e.g. 0x5455, 0x7875), stripped per-entry comments, and unconditionally forced flag 0x800 in XLSX.
6. **A18 (FAIL)**: UI retained pre-validation marketing wording ("kiểm chứng trung thực Lossless", "DOCX (Lossless)") and displayed fidelity claims before actual validator PASS.
7. **Audit Evidence Integrity**: `V2_2_RC2_HARDENING_EVIDENCE.json` referenced invented friendly test names instead of actual pytest node IDs.
8. **Browser Coverage**: 19-step smoke test did not test non-DOCX single cleaning (TXT, MD, PNG) or catch the `layer_a_only` API mismatch.

### Round 2 — Corrective Implementation
1. **A02 (Exact-Only Patcher)**:
   - Completely deleted the legacy `isinstance(mutations, (set, frozenset))` block in `service/scripts/docx/patcher.py`.
   - `DocxPatcher._patch_text_part` now accepts ONLY `Sequence[TextCodepointMutation]`. If a `set`, `frozenset`, or non-mutation is provided, it immediately raises `TypeError`.
   - Added witness test: duplicate codepoints in the same XML part mutate strictly at the planned coordinate offset; unauthorized duplicates remain intact.
2. **A08 (Unified Batch Semantics & Limits)**:
   - Created canonical `_normalize_batch_request(body, default_operation="clean")` in `server.py` enforcing:
     - 50 file cap (returns HTTP 413).
     - Strict top-level mode validation (SAFE, BALANCED, AGGRESSIVE; invalid mode returns HTTP 400).
     - Strict boolean `dry_run` validation.
     - Top-level `options` validation via `_parse_clean_options`.
     - 200 MiB aggregate batch payload cap (returns HTTP 413).
   - Unified both `/clean/batch` and `/batch` through `BatchProcessor.process_items`.
   - Updated `BatchProcessor.process_items` to propagate top-level options, mode, and dry-run, while preserving per-file fault isolation (32 MiB per-file limit).
3. **UI/API Clean Options Alignment**:
   - Updated `service/web/app.js` `cleanItem()` to send `{}` for formats that need no clean options, eliminating the invalid `layer_a_only` option.
   - Tested real single TXT, single Markdown, and single PNG cleaning via UI button click reaching canonical `/clean` with HTTP 200.
4. **A07 (Explicit Layer B Rejection Until P1)**:
   - In `service/scripts/server.py::_parse_clean_options()`, requests specifying `"strategy"` are explicitly rejected with HTTP 400 Bad Request:
     `"Advanced Statistical Layer B rewriting is not available in P0 canonical clean; Layer B is disabled until P1."`
   - Zero silent successes for unsupported rewrite requests.
5. **A11 (Changed-Entry ZIP Metadata Fidelity)**:
   - Created `_filter_safe_extra_fields` in `docx/package.py`, `xlsx/package.py`, and `pptx/package.py`.
   - Preserves safe compatible extra fields (e.g. Info-ZIP extended timestamps 0x5455, UNIX UID/GID 0x7875), entry comments, and disk number start.
   - Strips stale Zip64 headers (`0x0001`) during entry rebuilding to prevent size/offset corruption.
   - Removed unconditional `| 0x800` flag setting in XLSX, aligning with DOCX/PPTX to preserve original flag semantics (`orig_flags & ~0x08`).
6. **A18 (Complete UI Truthfulness)**:
   - Updated `service/web/index.html` lede text to: `"với kiểm chứng fidelity theo khả năng của từng định dạng."`
   - Removed `(Lossless)` format suffix in `service/web/app.js` `loadCapabilities()` and offline fallback.
   - Ensured `.badge-lossless` remains hidden until an actual validator PASS.
7. **Audit Evidence Integrity Reconciled**:
   - Replaced all invented test names in `V2_2_RC2_HARDENING_EVIDENCE.json` with exact collected pytest node IDs from `pytest --collect-only`.
   - Added automated verification test `test_evidence_test_ids_match_pytest_collection` in `tests/test_p0_round2_review_corrections.py`.
8. **Expanded Real Browser Coverage**:
   - Expanded `tests/smoke_browser.mjs` from 19 to 25 steps.
   - Added real headless Chrome testing for: single TXT clean, single Markdown clean, single PNG clean, multi-file batch (DOCX, TXT, MD, PNG), dynamic version display, and pre-validation truthfulness checks.

---

## 3. Immutable Release State

All historical release references remain verified and unmodified:

| Reference | Expected Target Commit | Observed Target Commit | Status |
|---|---|---|---|
| `v2.1.0-rc1` | `9ecfea135f7b871f226313bfc7f101d07f578d3b` | `9ecfea135f7b871f226313bfc7f101d07f578d3b` | **IMMUTABLE** |
| `v2.1.0` | `7a479f97ee0f034080e93beaf74e86d526956991` | `7a479f97ee0f034080e93beaf74e86d526956991` | **IMMUTABLE** |
| `v2.2.0-rc1` | `26244b3118f1b1d1cea7e4d2c1dfd9d814615125` | `26244b3118f1b1d1cea7e4d2c1dfd9d814615125` | **IMMUTABLE** |

No tags were moved, deleted, re-created, or force-pushed.

---

## 4. Issue Matrix

| ID | Severity | Status | Review Findings & History | Final Corrective Implementation | Real Pytest Verification Node IDs |
|---|---|---|---|---|---|
| **A01** | S1 | **FIXED** | 1-char lookback broke emoji + VS16 + ZWJ | State-aware emoji-glue bridge in `classify_stream` | `tests/test_rc2_hardening.py::test_a01_a04_emoji_vs16_zwj_classification`, `tests/test_docx_body_carriers.py` |
| **A02** | S1 | **FIXED** | R1: mutable plan; R2: legacy global codepoint set fallback | Removed set/frozenset fallback completely; exact `Sequence[TextCodepointMutation]` required; frozen mutation plan | `tests/test_rc2_hardening.py::test_a02_a15_exact_mutation_identity_same_codepoint`, `tests/test_p0_review_corrections.py::test_a02_docx_mutation_plan_immutability`, `tests/test_p0_round2_review_corrections.py::test_a02_docx_patcher_rejects_legacy_set_and_non_mutations`, `tests/test_p0_round2_review_corrections.py::test_a02_docx_witness_duplicate_codepoints_plan_authorizes_only_one` |
| **A03** | S1 | **FIXED** | Validator derived text by global stripping | Node-by-node reconciliation and closed-form conservation laws | `tests/test_rc2_hardening.py::test_a03_validator_catches_unauthorized_deletion` |
| **A04** | S1 | **FIXED** | DOCX maintained drifting contextual rules | Designated `text_unicode.py` as canonical authority | `tests/test_rc2_hardening.py::test_a01_a04_emoji_vs16_zwj_classification` |
| **A05** | S1 | **FIXED** | Context lost when emoji split across `<w:r>` | `ParagraphStream` aggregation in `docx/logical_stream.py` | `tests/test_rc2_hardening.py::test_a05_split_run_contextual_unicode` |
| **A06** | S1 | **FIXED** | `/clean` used dual-cleaner `_clean_payload` | Removed dual-cleaner; canonical `Pipeline.clean()` exclusively; guaranteed `SHA256(bytes) == report.output.sha256` | `tests/test_rc2_hardening.py::test_a06_returned_bytes_match_report_sha256`, `tests/test_p0_review_corrections.py::test_a06_clean_endpoint_canonical_sha256_invariant`, `tests/test_api_v21.py` |
| **A07** | S1 | **FIXED** | R1: required Layer B; R2: accepted strategy and silently ignored it | Explicitly reject `strategy` with HTTP 400 Bad Request until P1; normal clean is safe Layer A offline | `tests/test_rc2_hardening.py::test_a07_default_cleaning_layer_a_zero_network`, `tests/test_p0_review_corrections.py::test_a07_normal_clean_never_requires_layer_b`, `tests/test_clean_strategy.py::test_clean_text_normal_does_not_require_layer_b`, `tests/test_p0_round2_review_corrections.py::test_a07_normal_clean_with_strategy_explicitly_rejected` |
| **A08** | S2 | **FIXED** | R1: bypassed Pipeline; R2: ignored mode, dry_run, options, and limits | Unified `/clean/batch` and `/batch` via canonical `BatchProcessor`; enforced 50-file cap, 32 MiB per-file cap, 200 MiB aggregate cap, options and mode parity | `tests/test_rc2_hardening.py::test_a08_clean_batch_canonical_pipeline`, `tests/test_p0_review_corrections.py::test_a08_batch_parity_with_canonical_pipeline`, `tests/test_p0_round2_review_corrections.py::test_a08_batch_mode_propagation_safe_balanced_aggressive`, `tests/test_p0_round2_review_corrections.py::test_a08_batch_invalid_mode_rejected_with_400`, `tests/test_p0_round2_review_corrections.py::test_a08_batch_dry_run_propagation`, `tests/test_p0_round2_review_corrections.py::test_a08_batch_top_level_options_propagation`, `tests/test_p0_round2_review_corrections.py::test_a08_batch_limits_file_count_per_file_and_aggregate`, `tests/test_p0_round2_review_corrections.py::test_a08_semantic_parity_single_clean_clean_batch_and_batch` |
| **A09** | S2 | **MITIGATED / FIDELITY-SAFE** | Blanket `customXml/*` deletion dropped bound data | Checked `<w:dataBinding>`. Classified honestly as Mitigated / Fidelity-Safe | `tests/test_rc2_hardening.py::test_a09_customxml_databinding_preserved` |
| **A10** | S2 | **MITIGATED / FIDELITY-SAFE** | Blanket `docProps/custom.xml` deletion broke fields | Checked `DOCPROPERTY`. Classified honestly as Mitigated / Fidelity-Safe | `tests/test_rc2_hardening.py::test_a10_docprops_custom_docproperty_preserved` |
| **A11** | S2 | **FIXED** | R1: bit-3 descriptors; R2: stripped extra fields/comments, forced 0x800 in XLSX | Preserved compatible ZIP extra fields and comments; stripped stale Zip64; preserved original flag semantics across DOCX, XLSX, PPTX | `tests/test_rc2_hardening.py::test_a11_ooxml_zip_bit_3_cleared_on_modified_entries`, `tests/test_p0_review_corrections.py::test_a11_real_bit3_data_descriptor_docx`, `tests/test_p0_review_corrections.py::test_a11_real_bit3_data_descriptor_xlsx`, `tests/test_p0_review_corrections.py::test_a11_real_bit3_data_descriptor_pptx`, `tests/test_p0_round2_review_corrections.py::test_a11_docx_changed_entry_preserves_compatible_extra_fields_and_comment`, `tests/test_p0_round2_review_corrections.py::test_a11_xlsx_changed_entry_preserves_metadata_and_does_not_force_0x800`, `tests/test_p0_round2_review_corrections.py::test_a11_pptx_changed_entry_preserves_extra_fields_and_comment`, `tests/test_p0_round2_review_corrections.py::test_a11_stale_zip64_extra_field_stripped_on_rebuild` |
| **A12** | S2 | **FIXED** | Image cleaner stripped color ICC profiles | Preserved JPEG APP2 ICC and WebP ICCP chunks | `tests/test_rc2_hardening.py::test_a12_media_preserves_icc_profiles` |
| **A13** | S2 | **FIXED** | Untruthful surface reporting claims | Explicitly reported `visible_field_results: CHECKED`, `field_instructions_instrText: NOT_CHECKED`, `tracked_deletions_delText: NOT_CHECKED` | `tests/test_rc2_hardening.py::test_a13_surface_tracking_representation`, `tests/test_p0_review_corrections.py::test_a13_surface_coverage_truthfulness` |
| **A14** | S2 | **FIXED** | AI product names in generator metadata skipped | Ported upstream `8f58b8a` to `container_meta.py` | `tests/test_rc2_hardening.py::test_a14_ai_generator_product_names`, `tests/test_prose_values_not_provenance.py` |
| **A15** | S2 | **FIXED** | Regression fixtures lacked emoji+VS16+ZWJ | Added `counterexample_emoji_zwj.docx` & same-codepoint witness | `tests/test_docx_body_carriers.py` |
| **A16** | S2 | **FIXED** | Fixture MANIFEST.json and README drifted | Deterministically regenerated MANIFEST.json with SHA256 hashes | `tests/test_docx_body_carriers.py::test_manifest_integrity_and_cryptographic_provenance` |
| **A17** | S2 | **FIXED** | XLSX had `text_muts_by_orig` fallback; PPTX lacked exact identity | Removed XLSX text fallback; enforced exact identity by cell_ref / si_idx; patchers fail closed on unresolvable mutations; added duplicate text witnesses | `tests/test_rc2_hardening.py::test_a17_xlsx_pptx_plan_execution`, `tests/test_p0_review_corrections.py::test_a17_xlsx_duplicate_text_witness`, `tests/test_p0_review_corrections.py::test_a17_pptx_duplicate_text_witness` |
| **A18** | S3 | **FIXED** | R1: hardcoded v2.1; R2: layer_a_only bug on non-DOCX, pre-validation Lossless claims | Removed `layer_a_only: true`; neutral fidelity lede; removed `(Lossless)` format suffix; dynamic version display; badge strictly requires actual validator PASS | `tests/test_dry_run.py`, `tests/test_capabilities_endpoint.py`, `tests/test_p0_review_corrections.py::test_a18_ui_branding_and_dry_run_semantics`, `tests/test_p0_round2_review_corrections.py::test_a18_ui_pre_validation_truthfulness_no_lossless_overclaims`, `tests/test_p0_round2_review_corrections.py::test_ui_clean_non_docx_formats_reach_canonical_clean_successfully`, `tests/smoke_browser.mjs` |

---

## 5. Test Suite Execution & Verification

### Focused Round 2 Review Suite (`pytest tests/test_p0_round2_review_corrections.py`)
```
============================= test session starts =============================
collected 16 items
tests/test_p0_round2_review_corrections.py ................              [100%]
============================= 16 passed in 1.74s ==============================
```

### Combined P0 Review & RC2 Hardening Suites (`pytest tests/test_p0_review_corrections.py tests/test_rc2_hardening.py`)
```
============================= test session starts =============================
collected 25 items
tests/test_p0_review_corrections.py ...........                          [ 44%]
tests/test_rc2_hardening.py ..............                               [100%]
============================= 25 passed in 1.80s ==============================
```

### Evidence Integrity Verification
All 41 test node IDs referenced in `docs/audits/V2_2_RC2_HARDENING_EVIDENCE.json` resolve to genuine, collected pytest nodes verified by:
`tests/test_p0_round2_review_corrections.py::test_evidence_test_ids_match_pytest_collection` -> **PASS**.

### Real Browser Smoke Suite (`node tests/smoke_browser.mjs`)
- Browser: **Google Chrome 153.0.8010.48**
- Total Steps: **25/25 PASSED**
- Verified:
  - Steps 1-19: Capabilities, DOCX inspection, SAFE default, Dry Run preview, DOCX clean with Lossless badge, batch addition, partial failure isolation, UI reload, safe-only format protection, a11y, non-inline handling, XSS safety.
  - Step 20: Real single TXT clean via UI button click reaches `/clean` without HTTP 400.
  - Step 21: Real single Markdown clean via UI button click reaches `/clean` with download available.
  - Step 22: Real single PNG clean via UI button click reaches `/clean` with download available.
  - Step 23: Multi-file batch (DOCX, TXT, MD, PNG) processing with full single/batch parity.
  - Step 24: Dynamic version display matches server `/capabilities`.
  - Step 25: Pre-validation claims are truthful and neutral; badge only shows on verified pass.

### Full Pytest Regression Suite (`pytest tests/ -ra`)
- **2076 passed**, **152 skipped**, **0 failed**, **0 errors** in 245.69s (100% test pass rate across all formats, security limits, CLI, HTTP, and desktop lifecycles).

---

## 6. Final RC2 Gate Decision

```
======================================================================
P0 ROUND 2 CORRECTIVE: PASS (AWAITING INDEPENDENT REVIEW)
======================================================================
```

All 5 reopened issues (A02, A07, A08, A11, A18), the non-DOCX UI clean bug, and audit evidence integrity are fully resolved and verified. A09 and A10 remain correctly documented as `MITIGATED / FIDELITY-SAFE`.

**Next Action**: Commit changes normally, push branch `feature/v2.2.0-rc2-hardening` to GitHub, and await Independent Review Round 3 verification. DO NOT build RC2 packages, tag, or release.
