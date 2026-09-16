# Phase 2 Inspection-First & Dry-Run Engine Report

**Document Version:** 1.0.0  
**Branch:** `v2.1-dev`  
**Baseline Commit:** `758d3085b8868566209a82ea981a32aa61147a44` (v2.0.0)  
**Status:** PHASE 2 COMPLETE — READY FOR REVIEW  

---

## 1. Executive Summary

Phase 2 establishes strict **inspection-first** and **dry-run** semantics for the unified pipeline engine (`service/scripts/pipeline.py`), backed by the enriched data models in `service/scripts/pipeline_types.py`.

All core Phase 2 objectives have been implemented, tested, and verified:
1. **Strictly Read-Only Inspection**: `Pipeline.inspect()` never modifies source bytes, touches `mtime`, writes sibling files, or creates temporary directory artifacts. Tested across representative format fixtures.
2. **Deterministic Status Semantics**: Distinct status reporting distinguishes `DETECTED`, `NOT_DETECTED`, `NOT_CHECKED`, `UNAVAILABLE`, and `UNSUPPORTED`. No collapsed booleans.
3. **Structured Findings Model**: Fine-grained `Finding` records capture detector IDs, categories, confidence, actionability, part/location coordinates, codepoints, and metadata keys, with zero storage of full body text.
4. **Deterministic Mutation Preview & Parity**: Dry-run derives directly from the format engine's pre-execution `MutationPlan`. The invariant `dry_run mutation_plan == real clean pre-execution mutation_plan` is strictly proven.
5. **Zero-Write Guarantee**: `clean(..., dry_run=True)` executes zero disk writes (`safe_write_bytes`, `os.replace`, and file write modes patched/verified). `output.changed` remains `False`, while proposed changes are surfaced via `output.would_change`.
6. **Capability-Aware Processing**: Formats accurately report available detectors, unavailable detectors (e.g. missing external CLI tools like `exiftool`, `qpdf`), and unsupported checks based on `FormatPolicyRegistry`.
7. **Transparent Processing Modes**: `SAFE`, `BALANCED`, and `AGGRESSIVE` are accurately captured in `CleaningReport.policy.mode`. Where a format does not implement distinct aggressive mutations, explicit warnings are documented rather than fabricating destructive behavior.
8. **Network Isolation**: Strict local-only execution enforced; zero socket connections attempted during inspection or dry run.
9. **Privacy Invariant**: Serialized inspection and dry-run reports contain zero body text across all fixtures.
10. **Frozen DOCX Core Unmodified**: The frozen lossless DOCX engine (`service/scripts/docx/`) has zero diff against `v2.0.0`.

---

## 2. Frozen Subsystem & Baseline Regression

### 2.1 Frozen DOCX Engine Diff
```bash
git diff v2.0.0 -- service/scripts/docx/
```
**Result:** Empty (`0` changes). The v2.0 lossless DOCX core remains completely frozen.

### 2.2 Golden Baseline & Canonical Candidate Verification
- **Golden Baseline (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`)**:
  - Size: 49,959 bytes
  - SHA256: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d`
- **Canonical Candidate (`04_CANDIDATE_LOSSLESS_OUTPUT.docx`)**:
  - Size: 49,395 bytes
  - SHA256: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297`

Structural fidelity re-verification passed:
- Paragraph count invariant: 204 -> 204
- Run count invariant: 288 -> 288
- Page breaks invariant: 5 -> 5
- Rendered pages invariant: 19 -> 19 (visual evidence inherited from frozen v2.0 release)

---

## 3. Data Model & Architecture Extensions

### 3.1 Detection Status Enum (`DetectionStatus`)
Added to `service/scripts/pipeline_types.py`:
- `DETECTED`: High-confidence carrier/watermark markers were identified by active detectors.
- `NOT_DETECTED`: Active detectors inspected the file and identified no carrier/watermark markers.
- `NOT_CHECKED`: Category or marker class was not inspected for this format under current policy.
- `UNAVAILABLE`: Detector could not execute because an optional dependency or tool is missing.
- `UNSUPPORTED`: File format or container feature is not supported by any detector.

### 3.2 Structured Finding Model (`Finding`)
```python
@dataclass(frozen=True)
class Finding:
    detector_id: str
    category: str
    actionability: str
    confidence: float
    location: str
    target_part: str = ""
    codepoint: Optional[str] = None
    metadata_key: Optional[str] = None
    reason: str = ""
```
Only relevant fields are populated per finding type (e.g. `codepoint` for Unicode findings, `metadata_key` for container/image metadata). Full body text is never stored.

### 3.3 Enhanced Inspection & Output Records
- `InspectionData.unsupported_checks`: List of check categories not supported for this format.
- `InspectionData.detection_status`: Explicit `DetectionStatus` value.
- `OutputRecord.would_change`: Boolean flag indicating whether proposed mutations would alter the file on disk if executed without `--dry-run`.
- `OutputRecord.changed`: Remains strictly `False` on dry-run operations.

---

## 4. Verification & Invariant Proofs

The dedicated Phase 2 test suites demonstrate compliance with all specified invariants:

### 4.1 Read-Only Inspection Proof (`tests/test_inspection_first.py`)
- **Byte Identity**: Source SHA-256 is recorded before and after `inspect()`. Diff is strictly zero.
- **Timestamp Identity**: Exact nanosecond filesystem mtime (`os.stat().st_mtime_ns`) is identical before and after.
- **Directory Cleanliness**: Directory contents before and after are compared; zero temporary or sibling files are left behind.
- **Format Breadth**: Tested on DOCX (Golden), Plain Text, Markdown, PNG, PDF, and generic unsupported binary formats.

### 4.2 Dry-Run Zero-Write Guarantee (`tests/test_dry_run.py`)
- **Write Primitives Monkeypatched**: `common.safe_write_bytes`, `os.replace`, and write access via `builtins.open` were intercepted with assertion failures.
- **Result**: `clean(..., dry_run=True)` completed successfully with zero intercepted write invocations.
- **Status Semantics**:
  - Clean input with empty plan -> returns `NO_CHANGE_REQUIRED` (`would_change=False`, `changed=False`).
  - Input with proposed mutations -> returns `INSPECTED` (`would_change=True`, `changed=False`).

### 4.3 Mutation-Plan Parity & Plan Truthfulness (`tests/test_dry_run.py`)
- For the same input, processing mode, and policy:
  `dry_run mutation_plan.mutations == real clean pre_execution mutation_plan.mutations`
  `dry_run mutation_plan.changed_parts == real clean pre_execution mutation_plan.changed_parts`
- **Plan Truthfulness Invariant**: `test_docx_dry_run_plan_matches_actual_binary_mutations` proves that the planned effective changed parts in dry run (`{"docProps/core.xml", "docProps/app.xml"}`) identically match the actual binary uncompressed payload changed parts produced by the frozen cleaner.
- *Audit Note*: The True Golden (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`) contains no `customXml` parts. Planned metadata mutations target strictly `docProps/core.xml` (`lastModifiedBy`) and `docProps/app.xml` (`Application`), matching the canonical candidate byte-for-byte.

### 4.4 Processing Mode Propagation
- `SAFE`, `BALANCED`, and `AGGRESSIVE` are propagated to `report.policy.mode`.
- For formats where BALANCED/AGGRESSIVE have no additional operations, an explicit warning is added to `report.validation.warnings` stating that only SAFE operations exist. No destructive behavior is fabricated.

### 4.5 Universal Report Privacy
- Serialized inspection reports and dry-run reports were scanned against fixture body text across all test formats. Full text strings are strictly absent from reports.

### 4.6 Local Execution & Zero Network
- Socket connection attempts (`socket.socket.connect`, `socket.create_connection`) were monkeypatched to fail.
- All inspection and dry-run workflows executed completely local with 0 network calls.

---

## 5. Scope Boundaries & Deferred Acceptance

To maintain strict phase discipline:
- **Phase 3 CLI / API Normalization**: Deferred. `clean_file.py` and `inspect_file.py` remain legacy compatibility wrappers. Canonical CLI structure (`service/scripts/cli.py`) is reserved for Phase 3.
- **Phase 4 Batch Processing Engine**: Deferred.
- **Phase 7 & 8 XLSX / PPTX Lossless Adapters**: Deferred. XLSX/PPTX currently use policy definitions and standard container checks.
- **Phase 10 Multi-Format Idempotence Acceptance**: Deferred. DOCX idempotence is functionally active in the engine skeleton, but global multi-format idempotence acceptance is explicitly reserved for Phase 10.
- **ADR-010 Forwarder**: Dynamic `__getattr__` in `pipeline_types.py` is documented in ADR-010 as a temporary compatibility alias to be removed in Phase 3.

---

## 6. Test Suite Results

- Focused Phase 2 Suites:
  - `tests/test_inspection_first.py`: 7 passed
  - `tests/test_dry_run.py`: 7 passed
  - `tests/test_pipeline_data_model.py`: 9 passed
  - `tests/test_unified_pipeline.py`: 6 passed
- Full Regression Suite:
  - Total passed: **1388** (increased from Phase 1's 1374; +14 new Phase 2 invariant tests)
  - Total skipped: **152**
  - Total failed: **0**

