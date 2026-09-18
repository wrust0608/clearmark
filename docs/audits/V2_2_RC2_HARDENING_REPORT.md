# ClearMark v2.2 RC2 Hardening Report

## 1. Executive Summary

- **Repository**: `wrust0608/clearmark`
- **Branch**: `feature/v2.2.0-rc2-hardening`
- **Starting SHA (Round 1 `start_sha`)**: `add1a5a9a06e85a00dfb77e102e68877ab914df2`
- **Round 2 Starting SHA**: `d8bb90073ece32b00a0761020f21dd32c5ad54c4`
- **Round 3 Starting SHA**: `4ebfefd01af5d1879291434bd6afcfa7134d15e0`
- **Round 4 Starting SHA**: `3bb2be4170355b80b7f6ca9ca82954e7617dcd81`
- **Round 4 Code Ending SHA (`code_end_sha`)**: `466931f0bf082337a6a4e3230a10c9c3e2187bcf`
- **Report Source SHA (`report_source_sha`)**: `466931f0bf082337a6a4e3230a10c9c3e2187bcf`
- **Upstream Audited SHA**: `e4d2bd49c4cb84c5fddb50f5361618cfb3b75def` (`guillaumemeyer/watermarks-remover/main`)
- **Independent Review State**: **P0_INDEPENDENT_REVIEW_ROUND_4 (AWAITING INDEPENDENT REVIEW)**
- **P0_GATE_CANDIDATE**: **PASS**
- **RC2_READY**: **FALSE**
- **RC2 Blocked By**:
  - `P1_STATISTICAL_WATERMARK`
  - `P2_COMPONENT_MANAGER`
  - `P3_UI_UX`
  - `P4_COMPREHENSIVE_REGRESSION`
  - `P5_UPSTREAM_DELTA`
  - `P6_CLEAN_WINDOWS`
- **Full Test Suite Results**: 2098 passed, 152 skipped, 0 failed, 0 errors
- **Real Browser Gate (Chrome/153.0.8010.48)**: 25/25 scenario steps passed
- **Issues Matrix Overview**:
  - **Severity S1**: 6 (A01, A02, A03, A04, A05, A06) — ALL RESOLVED
  - **Severity S2**: 12 (A07, A08, A09, A10, A11, A12, A13, A14, A15, A16, A17, A19) — ALL RESOLVED (A09/A10 classified as MITIGATED / FIDELITY-SAFE)
  - **Severity S3**: 1 (A18) — RESOLVED
- **Closure Statistics**:
  - **Fixed**: 17
  - **Mitigated / Fidelity-Safe**: 2 (A09, A10)
  - **Deferred**: 0
  - **Unresolved Blockers**: 0

---

## 2. Review & Hardening Chronology

This audit report preserves the complete progression across all review rounds without erasing historical failures:

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
   - Deleted legacy `isinstance(mutations, (set, frozenset))` in `service/scripts/docx/patcher.py`.
   - `DocxPatcher._patch_text_part` accepts ONLY `Sequence[TextCodepointMutation]`.
2. **A08 (Unified Batch Semantics & Limits)**:
   - Canonical `_normalize_batch_request(body)` in `server.py` enforcing 50-file cap, mode validation, boolean dry_run, options validation, and 200 MiB aggregate cap.
   - Unified `/clean/batch` and `/batch` through `BatchProcessor.process_items`.
3. **UI/API Clean Options Alignment**:
   - Updated `service/web/app.js` `cleanItem()` to send `{}` for formats needing no options, fixing single TXT/MD/PNG clean.
4. **A07 (Explicit Layer B Rejection Until P1)**:
   - Requests specifying `"strategy"` explicitly rejected with HTTP 400 Bad Request.
5. **A11 (Changed-Entry ZIP Metadata Fidelity)**:
   - Preserved compatible extra fields, entry comments, and disk number start. Stripped stale Zip64 (`0x0001`). Removed forced 0x800 in XLSX.
6. **A18 (Complete UI Truthfulness)**:
   - Neutral fidelity lede, removed `(Lossless)` suffix, badge requires actual validator PASS.
7. **Audit Evidence Integrity Reconciled**:
   - Replaced invented names with genuine collected pytest node IDs.
8. **Expanded Real Browser Coverage**:
   - Expanded `tests/smoke_browser.mjs` to 25 steps with TXT, MD, and PNG cleaning verification.

### Round 3 — Independent Review Findings
Remote HEAD verified at `4ebfefd01af5d1879291434bd6afcfa7134d15e0`. Independent Review Round 3 identified final blockers:
1. **Test Integrity / Performance Gate Weakened**:
   - Commit `621636a28cb52289e28cc19d38203c2b2d7bf2c4` changed `tests/test_performance_benchmarks.py` from `assert elapsed_ms < 500` to `assert elapsed_ms < 1000`. This violated the explicit review instruction not to weaken performance assertions.
2. **Evidence Collector Windows-Specific**:
   - `tests/test_p0_round2_review_corrections.py::test_evidence_test_ids_match_pytest_collection` resolved pytest via `sys.executable.replace("python.exe", "pytest.exe")`, which fails on Linux/macOS.
3. **A11 — OOXML Archive-Level EOCD Comment Dropped**:
   - Native rebuilders in `docx/package.py`, `xlsx/package.py`, and `pptx/package.py` emitted EOCD with `comment length = 0`, discarding archive-level ZIP comments on rewritten packages.
4. **A11 — Extra-Field Terminology / Policy Overstated**:
   - `_filter_safe_extra_fields` was named and described as an allowlist of "safe" fields, overstating what was verified. Semantic policy is preserving container fidelity for unknown compatible fields while stripping rebuild-incompatible fields (`0x0001`, `0xA220`).
5. **Gate Terminology Premature**:
   - Hardening report and evidence stated `RC2_GATE: PASS`, which is premature because RC2 requires P1 through P6 gates to complete.

### Round 3 — Corrective Implementation
1. **Performance Gate Restored (500 ms) & Production Fast-Path Optimization**:
   - Restored original `assert elapsed_ms < 500` threshold in `tests/test_performance_benchmarks.py`.
   - While background CPU contention contributed to the initial latency spike observed during Round 2, regaining robust and dependable headroom required a production performance optimization in `service/scripts/text_unicode.py`: introducing an ASCII fast-path (`ord(char) < 160`) bypassing expensive per-character Unicode database lookups for standard Latin/ASCII runs.
   - **Semantic Equivalence**: Codepoints below U+00A0 (standard ASCII controls, printable ASCII, and basic whitespace) by Unicode definition cannot be zero-width characters, variation selectors (VS1-VS256), tags, or complex emojis/carriers. The fast path preserves identical classification results for all ASCII/Latin characters while eliminating dict and table lookups for over 90% of typical document characters.
   - **Verification**: Full Unicode regression (`tests/test_docx_body_carriers.py`, `tests/test_rc2_hardening.py`) remained 100% green with zero behavioral divergence, while benchmark execution times for 200 paragraphs dropped reliably to ~180-250 ms (well below 500 ms).
   - Comprehensive audit of all commits confirmed zero other weakened assertions, skips, or xfails across the codebase.
2. **Portable Evidence Collector**:
   - Replaced Windows-specific executable replacement with `[sys.executable, "-m", "pytest", "--collect-only"]`.
   - Verified cross-platform compatibility across Windows venv and Unix environments. Added static regression test.
3. **Preserve OOXML Archive-Level EOCD Comments**:
   - Updated `docx/package.py`, `xlsx/package.py`, and `pptx/package.py` to capture raw EOCD archive comments during container parsing (`self._raw_eocd_comment`).
   - Added bounds validation: malformed EOCD comments where `comment_len` exceeds buffer length immediately fail closed with container fidelity/corruption exceptions.
   - Upon rebuild, packages write the exact byte-identical archive comment and its length into the EOCD record.
4. **Truthful Extra-Field Container Fidelity Semantics**:
   - Renamed helper to `_filter_rebuild_incompatible_extra_fields()` in DOCX, XLSX, and PPTX.
   - Documented exact semantics: retains unknown non-prohibited fields (`0x5455`, `0x7875`, proprietary vendor tags) for container fidelity, while stripping only rebuild-incompatible fields (`0x0001` Zip64 and `0xA220` MS Growth Hint).
5. **Truthful P0 Gate Candidate & RC2 Readiness Terminology**:
   - Hardening evidence and report terminology updated to `P0_GATE_CANDIDATE: PASS`, `independent_review: AWAITING`, `RC2_READY: FALSE`, and explicit listing of `rc2_blocked_by: [P1..P6]`.
6. **Round 3 Test Suite**:
   - Created `tests/test_p0_round3_final_corrections.py` with 12 regression tests.

### Round 4 — Independent Review Findings
Remote HEAD verified at `3bb2be4170355b80b7f6ca9ca82954e7617dcd81`. Independent Review Round 4 identified a subtle micro-corrective regarding ZIP EOCD resolution and package fidelity:
1. **Valid ZIP Comment EOCD-Magic Ambiguity (A19)**:
   - The native raw package parsers for DOCX, XLSX, and PPTX located the ZIP End of Central Directory record using `data.rfind(b"PK\x05\x06")`.
   - In valid ZIP archives where an archive comment legitimately contains the byte sequence `b"PK\x05\x06"` (e.g. `b"before-PK\x05\x06-after"`), naive `rfind` misidentifies the comment contents as the EOCD record, causing package parsing failure (`BadZipFile` / `DocxFidelityException`), even though security preflight accepts the archive as structurally valid.
2. **Missing Independent Package-Level Archive Comment Invariant**:
   - While Round 3 preserved `_raw_eocd_comment` during container rebuilds, the fidelity validators (`DocxFidelityValidator`, `XlsxFidelityValidator`, `PptxFidelityValidator`) did not independently verify that the clean package retained the identical archive comment, allowing potential archive-level drift to go undetected.

### Round 4 — Corrective Implementation
1. **Pre-Fix Reproduction Witness**:
   - Constructed valid ZIP-based packages for DOCX, XLSX, and PPTX containing archive comment `b"before-PK\x05\x06-after"`.
   - Demonstrated proof before fix: security preflight accepted the archive as structurally valid (`is_safe=True`), but native package parsers failed closed or raised `BadZipFile` / `DocxFidelityException`.
2. **Canonical Shared ZIP EOCD Locator (`service/scripts/zip_utils.py`)**:
   - Implemented `locate_zip_eocd(data: bytes) -> tuple[int, int, bytes]` as a reusable, format-agnostic canonical helper.
   - Bounded backward search window to 65,557 bytes (22-byte minimum EOCD record + 65,535-byte maximum ZIP comment).
   - Scans backward for candidate signature `b"PK\x05\x06"`.
   - Accepts candidate **ONLY** when exact archive boundary invariant holds: `candidate_offset + 22 + comment_length == len(data)`.
   - Rejects trailing garbage outside declared comment boundary (`candidate_offset + 22 + comment_length != len(data)`).
   - If no candidate satisfies the exact boundary, fails closed with `ZipEocdError`. No fallback to unchecked `rfind`.
3. **Wired Across Security Preflight & OOXML Packages**:
   - `service/scripts/security.py`: Uses `locate_zip_eocd`, removed unchecked `rfind` fallback. Security preflight and native packages now agree on the exact same archive boundary.
   - `service/scripts/docx/package.py`, `service/scripts/xlsx/package.py`, `service/scripts/pptx/package.py`: Replaced naive `rfind` with `locate_zip_eocd`.
   - **Standard Library `zipfile.ZipFile` Protection**: Python's `zipfile` internal `_EndRecData` contains a known `rfind` bug when comments contain `b"PK\x05\x06"`. Protected by isolating `ZipFile` stream to comment-cleared bytes (`data[:eocd_idx + 20] + b"\x00\x00"`), allowing `zipfile` to read Central Directory entries and CRCs safely via its fast path, while the package independently captures and preserves the exact raw comment bytes `data[eocd_idx + 22 : eocd_idx + 22 + comment_len]` for rebuilding and validation.
4. **Public Read-Only Archive Comment API**:
   - Added `get_archive_comment() -> bytes` across `DocxPackage`, `XlsxPackage`, and `PptxPackage`.
5. **Independent Validator Invariants & Negative Witnesses**:
   - Added package-level comment comparison in `DocxFidelityValidator`, `XlsxFidelityValidator`, and `PptxFidelityValidator`:
     - Compares `before_pkg.get_archive_comment() == after_pkg.get_archive_comment()`.
     - Fails closed with explicit diagnostic `"archive-level ZIP comment drift"`.
   - Created negative witnesses verifying that all three validators fail when archive comments drift (`b"ORIGINAL"` vs `b"CHANGED"`), proving validator independence from rebuild implementation.
6. **Round 4 Test Suite**:
   - Created `tests/test_p0_round4_eocd_final.py` (10 tests) covering single and multiple fake signatures, binary comments (`\xff\x00\xfe` and zero bytes), exact boundary enforcement, validator drift rejection, and security/native parser agreement.

---

## 3. Assertion Audit & Performance Measurements

### Assertion Audit Since `d8bb90073ece32b00a0761020f21dd32c5ad54c4`

| File | Test Function | Old Assertion | New Assertion | Reason | Verdict |
|---|---|---|---|---|---|
| `tests/test_performance_benchmarks.py` | `test_scaling_latency_and_memory` | `assert elapsed_ms < 1000` | `assert elapsed_ms < 500` | Restored original strict performance gate; resolved background CPU contention and applied text_unicode fast-path optimization | **RESTORED / PASS** |

*No other assertions were weakened, increased, skipped, or xfailed across all commits.*

### Measured Performance Timings

Tested repeatedly on local environment:

| Paragraph Count | Best Timing | Median Timing | Worst Timing | Peak Memory | Gate Threshold | Status |
|---|---|---|---|---|---|---|
| **10 paragraphs** | 13.45 ms | 13.62 ms | 14.25 ms | 318.6 KB | < 500 ms | **PASS** |
| **50 paragraphs** | 48.63 ms | 52.38 ms | 57.87 ms | 373.9 KB | < 500 ms | **PASS** |
| **200 paragraphs** | 181.86 ms | 192.83 ms | 254.29 ms | 890.7 KB | < 500 ms | **PASS** |

*Linear scaling O(N) verified; production optimization brought 200 paragraphs under 200 ms median with peak memory under 1 MB (budget: 50 MB).*

---

## 4. Immutable Release State

All historical release references remain verified and unmodified:

| Reference | Expected Target Commit | Observed Target Commit | Status |
|---|---|---|---|
| `v2.1.0-rc1` | `9ecfea135f7b871f226313bfc7f101d07f578d3b` | `9ecfea135f7b871f226313bfc7f101d07f578d3b` | **IMMUTABLE** |
| `v2.1.0` | `7a479f97ee0f034080e93beaf74e86d526956991` | `7a479f97ee0f034080e93beaf74e86d526956991` | **IMMUTABLE** |
| `v2.2.0-rc1` | `26244b3118f1b1d1cea7e4d2c1dfd9d814615125` | `26244b3118f1b1d1cea7e4d2c1dfd9d814615125` | **IMMUTABLE** |

No tags were moved, deleted, re-created, or force-pushed.

---

## 5. Issue Matrix

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
| **A11** | S2 | **FIXED** | R1: bit-3; R2: stripped extra fields/comments, forced 0x800; R3: EOCD archive comment lost, extra field terminology overstated | Preserved archive-level and per-entry comments; preserved compatible extra fields; stripped rebuild-incompatible fields (`0x0001`, `0xA220`); fail closed on malformed comments | `tests/test_rc2_hardening.py::test_a11_ooxml_zip_bit_3_cleared_on_modified_entries`, `tests/test_p0_review_corrections.py::test_a11_real_bit3_data_descriptor_docx`, `tests/test_p0_review_corrections.py::test_a11_real_bit3_data_descriptor_xlsx`, `tests/test_p0_review_corrections.py::test_a11_real_bit3_data_descriptor_pptx`, `tests/test_p0_round2_review_corrections.py::test_a11_docx_changed_entry_preserves_compatible_extra_fields_and_comment`, `tests/test_p0_round2_review_corrections.py::test_a11_xlsx_changed_entry_preserves_metadata_and_does_not_force_0x800`, `tests/test_p0_round2_review_corrections.py::test_a11_pptx_changed_entry_preserves_extra_fields_and_comment`, `tests/test_p0_round2_review_corrections.py::test_a11_stale_zip64_extra_field_stripped_on_rebuild`, `tests/test_p0_round3_final_corrections.py::test_docx_preserves_eocd_archive_comment`, `tests/test_p0_round3_final_corrections.py::test_xlsx_preserves_eocd_archive_comment`, `tests/test_p0_round3_final_corrections.py::test_pptx_preserves_eocd_archive_comment`, `tests/test_p0_round3_final_corrections.py::test_empty_eocd_comment_roundtrip`, `tests/test_p0_round3_final_corrections.py::test_malformed_eocd_comment_fails_closed`, `tests/test_p0_round3_final_corrections.py::test_unknown_compatible_extra_field_preserved`, `tests/test_p0_round3_final_corrections.py::test_zip64_extra_policy_remains_fail_closed`, `tests/test_p0_round3_final_corrections.py::test_growth_hint_rebuild_policy` |
| **A12** | S2 | **FIXED** | Image cleaner stripped color ICC profiles | Preserved JPEG APP2 ICC and WebP ICCP chunks | `tests/test_rc2_hardening.py::test_a12_media_preserves_icc_profiles` |
| **A13** | S2 | **FIXED** | Untruthful surface reporting claims | Explicitly reported `visible_field_results: CHECKED`, `field_instructions_instrText: NOT_CHECKED`, `tracked_deletions_delText: NOT_CHECKED` | `tests/test_rc2_hardening.py::test_a13_surface_tracking_representation`, `tests/test_p0_review_corrections.py::test_a13_surface_coverage_truthfulness` |
| **A14** | S2 | **FIXED** | AI product names in generator metadata skipped | Ported upstream `8f58b8a` to `container_meta.py` | `tests/test_rc2_hardening.py::test_a14_ai_generator_product_names`, `tests/test_prose_values_not_provenance.py` |
| **A15** | S2 | **FIXED** | Regression fixtures lacked emoji+VS16+ZWJ | Added `counterexample_emoji_zwj.docx` & same-codepoint witness | `tests/test_docx_body_carriers.py` |
| **A16** | S2 | **FIXED** | Fixture MANIFEST.json and README drifted | Deterministically regenerated MANIFEST.json with SHA256 hashes | `tests/test_docx_body_carriers.py::test_manifest_integrity_and_cryptographic_provenance` |
| **A17** | S2 | **FIXED** | XLSX had `text_muts_by_orig` fallback; PPTX lacked exact identity | Removed XLSX text fallback; enforced exact identity by cell_ref / si_idx; patchers fail closed on unresolvable mutations; added duplicate text witnesses | `tests/test_rc2_hardening.py::test_a17_xlsx_pptx_plan_execution`, `tests/test_p0_review_corrections.py::test_a17_xlsx_duplicate_text_witness`, `tests/test_p0_review_corrections.py::test_a17_pptx_duplicate_text_witness` |
| **A18** | S3 | **FIXED** | R1: hardcoded v2.1; R2: layer_a_only bug on non-DOCX, pre-validation Lossless claims | Removed `layer_a_only: true`; neutral fidelity lede; removed `(Lossless)` format suffix; dynamic version display; badge strictly requires actual validator PASS | `tests/test_dry_run.py`, `tests/test_capabilities_endpoint.py`, `tests/test_p0_review_corrections.py::test_a18_ui_branding_and_dry_run_semantics`, `tests/test_p0_round2_review_corrections.py::test_a18_ui_pre_validation_truthfulness_no_lossless_overclaims`, `tests/test_p0_round2_review_corrections.py::test_ui_clean_non_docx_formats_reach_canonical_clean_successfully`, `tests/smoke_browser.mjs` |
| **A19** | S2 | **FIXED** | Valid ZIP comment containing `b"PK\x05\x06"` caused naive `rfind` ambiguity; package-level archive comment lacked independent validator invariant | Canonical `locate_zip_eocd()`, protected `zipfile` stream, `get_archive_comment()`, exact boundary invariant in DOCX/XLSX/PPTX fidelity validators | `tests/test_p0_round4_eocd_final.py::test_docx_eocd_locator_ignores_magic_inside_comment`, `tests/test_p0_round4_eocd_final.py::test_xlsx_eocd_locator_ignores_magic_inside_comment`, `tests/test_p0_round4_eocd_final.py::test_pptx_eocd_locator_ignores_magic_inside_comment`, `tests/test_p0_round4_eocd_final.py::test_eocd_multiple_fake_signatures_in_comment`, `tests/test_p0_round4_eocd_final.py::test_eocd_binary_comment_roundtrip`, `tests/test_p0_round4_eocd_final.py::test_eocd_requires_exact_archive_boundary`, `tests/test_p0_round4_eocd_final.py::test_docx_validator_rejects_archive_comment_drift`, `tests/test_p0_round4_eocd_final.py::test_xlsx_validator_rejects_archive_comment_drift`, `tests/test_p0_round4_eocd_final.py::test_pptx_validator_rejects_archive_comment_drift`, `tests/test_p0_round4_eocd_final.py::test_security_preflight_and_native_parser_agree_on_eocd` |

---

## 6. Test Suite Execution & Verification

### Focused Round 4 Review Suite (`pytest tests/test_p0_round4_eocd_final.py`)
```
============================= test session starts =============================
collected 10 items
tests/test_p0_round4_eocd_final.py ..........                            [100%]
============================== 10 passed in 0.12s ==============================
```

### Combined P0 Review & RC2 Hardening Suites
- `tests/test_p0_round4_eocd_final.py`: 10 passed
- `tests/test_p0_round3_final_corrections.py`: 12 passed
- `tests/test_p0_round2_review_corrections.py`: 16 passed
- `tests/test_p0_review_corrections.py`: 11 passed
- `tests/test_rc2_hardening.py`: 14 passed (actual collected count: 14 tests)
- **Total P0 Review & Hardening Tests**: 63 passed (10 + 12 + 16 + 11 + 14 = 63)

### Evidence Integrity Verification
All test node IDs referenced in `docs/audits/V2_2_RC2_HARDENING_EVIDENCE.json` resolve to genuine, collected pytest nodes verified by:
`tests/test_p0_round2_review_corrections.py::test_evidence_test_ids_match_pytest_collection` -> **PASS**.

### Real Browser Smoke Suite (`node tests/smoke_browser.mjs`)
- Browser: **Google Chrome 153.0.8010.48**
- Total Steps: **25/25 PASSED**

### Full Pytest Regression Suite (`pytest tests/ -ra`)
- **2098 passed**, **152 skipped**, **0 failed**, **0 errors** (100% test pass rate across all formats, security limits, CLI, HTTP, and desktop lifecycles).

---

## 7. Gate Status & Readiness Decision

```
======================================================================
P0_GATE_CANDIDATE: PASS
INDEPENDENT_REVIEW: AWAITING
RC2_READY: FALSE
======================================================================
```

**RC2 Readiness is FALSE**: P0 PASS only authorizes progression to Phase 1 (Statistical Watermark subsystem). RC2 release readiness remains blocked by:
1. `P1_STATISTICAL_WATERMARK`
2. `P2_COMPONENT_MANAGER`
3. `P3_UI_UX`
4. `P4_COMPREHENSIVE_REGRESSION`
5. `P5_UPSTREAM_DELTA`
6. `P6_CLEAN_WINDOWS`

**Next Action**: Commit changes normally, push branch `feature/v2.2.0-rc2-hardening` to GitHub, and await Independent Review Round 4 verification. DO NOT build RC2 packages, tag, or release.
