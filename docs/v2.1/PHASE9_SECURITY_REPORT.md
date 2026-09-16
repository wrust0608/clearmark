# Phase 9: Malformed File Hardening & Security Preflight Report

## 1. Executive Summary & Scope Statement

Phase 9 establishes a centralized, format-neutral container and XML security preflight layer ([`security.py`](file:///service/scripts/security.py)) for ClearMark v2.1.
In accordance with the project security principle **"REJECT BEFORE MUTATION"**, all untrusted archive containers and embedded XML payloads are strictly validated before any format-specific parsing, adapter invocation, or mutation logic executes.

All 38 declared threats from the Phase 9 Threat Matrix ([`PHASE9_SECURITY_THREAT_MATRIX.md`](file:///docs/v2.1/PHASE9_SECURITY_THREAT_MATRIX.md)) are verified against deterministic synthetic hostile fixtures in `tests/fixtures/security/` and validated in [`test_malformed_archives.py`](file:///tests/test_malformed_archives.py).

> [!IMPORTANT]
> **Scope Statement**: The declared Phase 9 hostile corpus is rejected under the configured SecurityLimits, with canonical public workflows protected before format-specific mutation. The implementation provides defense-in-depth resource governance and fail-closed structural validation without modifying the frozen DOCX core (`service/scripts/docx/*`).

---

## 2. Security Architecture & Threat Boundaries

### 2.1 One Security Layer Architecture
The container and XML security preflight engine is housed exclusively in:
- [`service/scripts/security.py`](file:///service/scripts/security.py)

Per architectural rules, no format-local duplicate preflights (`service/scripts/docx/security.py`, `service/scripts/xlsx/security.py`, `service/scripts/pptx/security.py`) exist. Format-specific fidelity validators (`DocxFidelityValidator`, `XlsxFidelityValidator`, `PptxFidelityValidator`) remain strictly separated and govern post-cleaning structural semantic invariants.

```
Incoming Untrusted Bytes
        │
        ▼
[ Cheap Magic & Length Probe ] (Phase 9 Preflight Hook)
        │
        ▼
[ Security Preflight Layer: service/scripts/security.py ]
    ├── Phase 1: Binary Structural Integrity (EOCD, CD bounds, Local headers, Overlap, Multi-disk, ZIP64)
    ├── Phase 2: Path Safety & Member Sanity (ZipSlip, Traversal, Duplicates, Symlinks, Encryption)
    ├── Phase 3: Resource Bounds & Streaming Decompression (Member count, Expansion, Bomb ratio, CRC)
    └── Phase 4: Streaming XML Preflight (Part size, Element count, Depth limit, DTD/XXE rejection)
        │
        ├── FAILS ──> SecurityViolation (Fail-Closed, Zero Mutation, ExitCode 4 or 6, HTTP 400 or 413)
        │
        ▼ PASSES
[ Safe Format Classification ] (DOCX / XLSX / PPTX / Binary)
        │
        ▼
[ Format Adapters & Lossless Mutation ]
        │
        ▼
[ Format Fidelity Validation ]
        │
        ▼
Output Clean Document
```

### 2.2 Low-Level Direct-Call Trust Boundary
- **Public Workflows**: `Pipeline.inspect`, `Pipeline.clean`, `BatchProcessor`, `watermarks` CLI (`inspect`, `clean`, `batch`, `verify`), and HTTP endpoints (`/inspect`, `/clean`, `/verify`, `/batch`) are unconditionally guarded by `security.py`.
- **Low-Level Adapters**: Low-level function `clean_docx_lossless` resides in the frozen DOCX core (`service/scripts/docx/`), which remains 100% byte-for-byte identical to v2.0.0. Callers invoking `clean_docx_lossless` directly bypass preflight unless mediated by `clean_container`, `clean_docx`, or `Pipeline`. Low-level `clean_xlsx_lossless` and `clean_pptx_lossless` retain internal package validation, but external untrusted data entry is routed through `Pipeline` or `container_meta`.

---

## 3. Authoritative Security Limits (`SecurityLimits`)

### 3.1 Runtime Defaults & Source of Truth
[`SecurityLimits`](file:///service/scripts/security.py#L69-L116) in `service/scripts/security.py` is the single source of truth for all operational limits.

| Field Name | Runtime Default | Meaning |
| :--- | :--- | :--- |
| `max_member_count` | `10,000` | Maximum number of entries in Central Directory |
| `max_member_uncompressed_bytes` | `67,108,864` (64 MiB) | Maximum uncompressed bytes for any single member |
| `max_total_uncompressed_bytes` | `134,217,728` (128 MiB) | Maximum cumulative uncompressed bytes across all members |
| `max_compression_ratio` | `100.0` | Maximum allowable expansion ratio (`uncompressed / effective_comp`) |
| `min_compressed_bytes_for_ratio` | `1,024` (1 KiB) | Ratio evaluation floor to prevent false positives on tiny members |
| `max_member_name_bytes` | `1,024` (1 KiB) | Maximum filename byte length |
| `max_xml_part_bytes` | `33,554,432` (32 MiB) | Maximum byte size of any single XML / RELS part |
| `max_total_xml_bytes` | `134,217,728` (128 MiB) | Maximum cumulative XML bytes across entire archive |
| `max_xml_depth` | `100` | Maximum element nesting depth |
| `max_xml_elements` | `500,000` | Maximum total element count per XML part |
| `chunk_size` | `65,536` (64 KiB) | Buffer size for streaming decompression & hash calculation |

### 3.2 Environment Variable Overrides & Safe Fallback
All limits support optional runtime override via `WATERMARKS_SECURITY_*` environment variables:

| Environment Variable | Target Field | Default | Valid Min | Fallback Behavior on Invalid Value |
| :--- | :--- | :--- | :--- | :--- |
| `WATERMARKS_SECURITY_MAX_MEMBER_COUNT` | `max_member_count` | `10000` | `1` | Falls back safely to `10000` |
| `WATERMARKS_SECURITY_MAX_MEMBER_UNCOMPRESSED_BYTES` | `max_member_uncompressed_bytes` | `67108864` | `1` | Falls back safely to `67108864` |
| `WATERMARKS_SECURITY_MAX_TOTAL_UNCOMPRESSED_BYTES` | `max_total_uncompressed_bytes` | `134217728` | `1` | Falls back safely to `134217728` |
| `WATERMARKS_SECURITY_MAX_COMPRESSION_RATIO` | `max_compression_ratio` | `100.0` | `1.0` | Falls back safely to `100.0` |
| `WATERMARKS_SECURITY_MIN_COMPRESSED_BYTES_FOR_RATIO` | `min_compressed_bytes_for_ratio` | `1024` | `0` | Falls back safely to `1024` |
| `WATERMARKS_SECURITY_MAX_MEMBER_NAME_BYTES` | `max_member_name_bytes` | `1024` | `1` | Falls back safely to `1024` |
| `WATERMARKS_SECURITY_MAX_XML_PART_BYTES` | `max_xml_part_bytes` | `33554432` | `1` | Falls back safely to `33554432` |
| `WATERMARKS_SECURITY_MAX_TOTAL_XML_BYTES` | `max_total_xml_bytes` | `134217728` | `1` | Falls back safely to `134217728` |
| `WATERMARKS_SECURITY_MAX_XML_DEPTH` | `max_xml_depth` | `100` | `1` | Falls back safely to `100` |
| `WATERMARKS_SECURITY_MAX_XML_ELEMENTS` | `max_xml_elements` | `500000` | `1` | Falls back safely to `500000` |

If an environment value is non-numeric, negative, or below the minimum valid bound, `_env_int` / `_env_float` logs/traps the exception and reverts to the hard-coded default. Production stability is never compromised by malformed configuration.

### 3.3 Safety Margin Empirical Verification
Production defaults were selected after empirical measurement of valid document corpora across DOCX, XLSX, and PPTX (Golden DOCX, Phase 6, Phase 7, Phase 8 suites):

| Metric | Measured Corpus Max | Production Limit | Safety Margin |
| :--- | :--- | :--- | :--- |
| **Member Count** | 21 entries | 10,000 entries | **476x** margin |
| **Member Uncompressed Size** | 345,277 B (~337 KiB) | 67,108,864 B (64 MiB) | **194x** margin |
| **Total Uncompressed Size** | 616,405 B (~602 KiB) | 134,217,728 B (128 MiB) | **217x** margin |
| **Compression Ratio** | 24.5 | 100.0 | **4.08x** margin |
| **XML Part Size** | 345,277 B (~337 KiB) | 33,554,432 B (32 MiB) | **97x** margin |
| **XML Nesting Depth** | 13 levels | 100 levels | **7.69x** margin |
| **XML Element Count** | 8,701 elements | 500,000 elements | **57x** margin |

Legitimate office documents operate well below these thresholds, while hostile expansion bombs and parser-exhaustion vectors are reliably blocked.

---

## 4. Deep Parser Implementation Details

### 4.1 Expat-Based Streaming XML Parser
Streaming XML inspection is implemented via Python stdlib `xml.parsers.expat.ParserCreate()`.
- **Event-Driven Non-Recursive Traversal**: The parser uses `StartElementHandler` and `EndElementHandler` callbacks to increment/decrement integer depth and element counters.
- **Zero DOM Tree Overhead**: No AST, ElementTree nodes, or DOM structures are allocated. Memory overhead is strictly $O(1)$ with respect to XML tree structure, guaranteeing bounded memory even on parts approaching the 32 MiB limit.
- **Encoding Preflight**: Before parsing, an encoding probe inspects the XML declaration and BOMs (supporting UTF-8, UTF-8 BOM, UTF-16 LE BOM, UTF-16 BE BOM, and ISO-8859-1) to detect prohibited `<!DOCTYPE` or `<!ENTITY` blocks across character sets.
- **Zero Network XXE**: External DTDs, parameter entities, and external general entities (`SYSTEM` / `PUBLIC`) are intercepted and rejected upfront. Test witnesses verified **0 network connection attempts** and **0 socket invocations**.

### 4.2 Member Byte Range Overlap Validation
Physical member byte ranges are calculated to account for the full physical footprint, including any trailing data descriptor:
$$\text{physical\_end} = \text{local\_header\_offset} + 30 + \text{local\_name\_length} + \text{local\_extra\_length} + \text{compressed\_size} + \text{descriptor\_length}$$
where $\text{descriptor\_length}$ is:
- `0` when General Purpose Bit 3 is not set.
- `12` for an unsigned data descriptor (CRC32, compressed size, uncompressed size) when Bit 3 is set.
- `16` for a signed data descriptor (`PK\x07\x08` signature + CRC32, compressed size, uncompressed size) when Bit 3 is set.

All member spans are sorted by start offset. If $\text{start}_{i+1} < \text{physical\_end}_i$, the archive is immediately rejected (`SEC_OVERLAPPING_MEMBERS`), defeating zip-within-zip hiding techniques, descriptor overlap exploits, and local-header overlap confusion attacks.

### 4.3 Data Descriptor Handling (Bit 3) & Consistency Validation
When General Purpose Bit 3 is set:
- **Supported Policies**: Both signed (16 bytes, signature `0x08074B50`) and unsigned (12 bytes, without signature) data descriptors are `SUPPORTED_AND_VALIDATED` for non-ZIP64 archives. ZIP64 descriptors remain explicitly unsupported and fail-closed.
- **Strict Field Validation**: The data descriptor immediately following the compressed payload is parsed and verified against the authoritative Central Directory record:
  - $\text{descriptor CRC32} == \text{Central Directory CRC32}$
  - $\text{descriptor compressed size} == \text{Central Directory compressed size}$
  - $\text{descriptor uncompressed size} == \text{Central Directory uncompressed size}$
  Any mismatch raises `SEC_DATA_DESCRIPTOR_MISMATCH` (fail-closed).
- **Flag Consistency**: Bit 3 and Bit 0 (encryption) must be strictly identical between Local File Header flags and Central Directory flags. Mismatches raise `SEC_LOCAL_CENTRAL_MISMATCH`.
- **Non-Bit-3 Size Consistency**: When Bit 3 is not set, Local File Header CRC32, compressed size, and uncompressed size must match Central Directory values exactly (`SEC_LOCAL_CENTRAL_MISMATCH`).
- **Signature Disambiguation & Local Header Offset Authority**: Local header boundaries are driven exclusively by Central Directory offsets, never arbitrary signature scans. Descriptors or payloads containing bytes identical to `PK\x03\x04` (`0x04034B50`) cannot masquerade as fake local headers.

### 4.4 EOCD Comment & Trailing Data Validation
- The End of Central Directory record is located within the final 65,557 bytes.
- The declared comment length must satisfy: $\text{eocd\_pos} + 22 + \text{comment\_len} == \text{data\_len}$.
- Any unexplained trailing bytes beyond the EOCD record and declared comment cause immediate rejection (`SEC_TRUNCATED_EOCD` / `SEC_MISSING_EOCD`), preventing stealth appended payloads.

### 4.5 Comprehensive ZIP64 Detection (Fail-Closed)
ClearMark enforces an unambiguous fail-closed policy against ZIP64 archives (`SEC_ZIP64_UNSUPPORTED`):
- ZIP64 EOCD Locator signature (`PK\x06\x07`)
- ZIP64 EOCD Record signature (`PK\x06\x06`)
- EOCD 16/32-bit sentinels (`0xFFFF` member counts or `0xFFFFFFFF` offsets/sizes)
- ZIP64 Extra Field (Header ID `0x0001`) in Central Directory extra fields AND Local File Header extra fields

---

## 5. Public Contract & Verification Error Semantics

### 5.1 Preflight Before Mutation
In all entry points (`Pipeline.inspect`, `Pipeline.clean`, CLI, HTTP API), preflight runs before format dispatch. Dry-run (`dry_run=True`) does NOT bypass security preflight. Hostile inputs emit zero output files and invoke zero format adapters.

### 5.2 Verify Workflow Error Semantics
The `watermarks verify <original> <candidate>` CLI command and `POST /verify` HTTP endpoint distinguish container/resource security preflight failures from semantic fidelity validation failures:

| Scenario | Input Evaluated | Error Category | Exit Code | HTTP Status | Status Field | Fidelity Validator Run? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Malformed Original | `original` | `INVALID_CONTAINER` | `4` | `400 Bad Request` | `"ERROR"` | **NO** (Skipped) |
| Malformed Candidate | `candidate` | `INVALID_CONTAINER` | `4` | `400 Bad Request` | `"ERROR"` | **NO** (Skipped) |
| Limit-Exceeded Original | `original` | `PROCESSING_LIMIT_EXCEEDED` | `6` | `413 Payload Too Large` | `"ERROR"` | **NO** (Skipped) |
| Limit-Exceeded Candidate | `candidate` | `PROCESSING_LIMIT_EXCEEDED` | `6` | `413 Payload Too Large` | `"ERROR"` | **NO** (Skipped) |
| Safe Candidate Violating Fidelity | `candidate` | `VALIDATION_FAILED` | `3` | `422 Unprocessable Entity` | `"FAIL"` | **YES** |

Preflight failure reasons preserve the underlying rule identifier (e.g. `SEC_ZIPSLIP_PARENT`, `SEC_XML_DEPTH_LIMIT`, `SEC_OVERLAPPING_MEMBERS`) without leaking confidential document contents or raw text.

---

## 6. Canonical Appendix: Full 38-Threat Traceability Table

The following table provides machine- and auditor-traceable evidence mapping every threat in [`PHASE9_SECURITY_THREAT_MATRIX.md`](file:///docs/v2.1/PHASE9_SECURITY_THREAT_MATRIX.md) to its rule ID, synthetic fixture, executable test, CLI code, HTTP code, and verification result.

| Threat ID | Threat Category / Vector | Rule ID | Fixture File | Exact Test Name | Expected ErrorCode | CLI | HTTP | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **THREAT-01** | ZipSlip: Relative Traversal (`../evil.xml`) | `SEC_ZIPSLIP_PARENT` | `zipslip_parent_traversal.zip` | `test_threat_01_zipslip_relative_traversal` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-02** | ZipSlip: Absolute Unix Path (`/etc/passwd`) | `SEC_ZIPSLIP_ABSOLUTE` | `zipslip_absolute_unix.zip` | `test_threat_02_zipslip_absolute_unix_path` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-03** | ZipSlip: Windows Drive (`C:\evil.xml`) | `SEC_ZIPSLIP_WINDOWS_DRIVE` | `zipslip_windows_drive.zip` | `test_threat_03_zipslip_windows_drive` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-04** | ZipSlip: Backslash Traversal (`a\..\b`) | `SEC_ZIPSLIP_BACKSLASH` | `zipslip_backslash.zip` | `test_threat_04_zipslip_backslash` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-05** | ZipSlip: UNC Path (`\\server\share\evil`) | `SEC_ZIPSLIP_UNC` | `zipslip_unc_path.zip` | `test_threat_05_zipslip_unc_path` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-06** | ZipSlip: NUL Byte Injection (`evil.xml\0.txt`) | `SEC_ZIPSLIP_NUL_BYTE` | `zipslip_nul_byte.zip` | `test_threat_06_zipslip_nul_byte` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-07** | Duplicate Member Names (Exact) | `SEC_DUPLICATE_MEMBER` | `duplicate_members.zip` | `test_threat_07_duplicate_members` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-08** | Non-canonical Collisions (`a//b`, `a/./b`) | `SEC_NONCANONICAL_PATH` | `noncanonical_path_collision.zip` | `test_threat_08_noncanonical_path_collisions` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-09** | ZIP Symlink Entries (`S_IFLNK`) | `SEC_SYMLINK_MEMBER` | `symlink_entry.zip` | `test_threat_09_zip_symlink_entry` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-10** | Encrypted ZIP Members (Bit 0) | `SEC_ENCRYPTED_MEMBER` | `encrypted_entry.zip` | `test_threat_10_encrypted_member` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-11** | Unsupported Compression Method | `SEC_UNSUPPORTED_COMPRESSION` | `unsupported_compression.zip` | `test_threat_11_unsupported_compression` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-12** | Archive Member Count Bomb | `SEC_MEMBER_COUNT_LIMIT` | `member_count_limit.zip` | `test_threat_12_archive_member_count_bomb` | `PROCESSING_LIMIT_EXCEEDED` | 6 | 413 | **PASS** |
| **THREAT-13** | Single-Member Uncompressed Bomb | `SEC_MEMBER_UNCOMPRESSED_LIMIT` | `member_uncompressed_limit.zip` | `test_threat_13_single_member_uncompressed_bomb` | `PROCESSING_LIMIT_EXCEEDED` | 6 | 413 | **PASS** |
| **THREAT-14** | Total Uncompressed Bomb (Cumulative) | `SEC_TOTAL_UNCOMPRESSED_LIMIT` | `total_uncompressed_limit.zip` | `test_threat_14_total_uncompressed_bomb` | `PROCESSING_LIMIT_EXCEEDED` | 6 | 413 | **PASS** |
| **THREAT-15** | ZipBomb Compression Amplification | `SEC_COMPRESSION_RATIO_LIMIT` | `compression_ratio_limit.zip` | `test_threat_15_zipbomb_compression_ratio` | `PROCESSING_LIMIT_EXCEEDED` | 6 | 413 | **PASS** |
| **THREAT-16** | Forged Metadata / Decompression Discrepancy | `SEC_TRUNCATED_STREAM` | `forged_metadata_discrepancy.zip` | `test_threat_16_forged_metadata_decompression_discrepancy` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-17** | CRC32 Mismatch / Corrupt Deflate | `SEC_CRC_MISMATCH` | `corrupted_crc32.zip` | `test_threat_17_crc32_and_corrupted_deflate` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-18** | Missing / Truncated EOCD Record | `SEC_MISSING_EOCD` | `corrupted_missing_eocd.zip` | `test_threat_18_missing_and_truncated_eocd` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-19** | Central Directory Out of Bounds | `SEC_BAD_CD_OFFSET` | `bad_cd_offset.zip` | `test_threat_19_central_directory_out_of_bounds` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-20** | Local File Header Out of Bounds | `SEC_BAD_LOCAL_HEADER_OFFSET` | `bad_local_header_offset.zip` | `test_threat_20_local_file_header_out_of_bounds` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-21** | Local vs Central Directory Mismatch | `SEC_LOCAL_CENTRAL_MISMATCH` | `local_central_filename_mismatch.zip` | `test_threat_21_local_vs_central_mismatch` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-22** | Overlapping Archive Member Ranges | `SEC_OVERLAPPING_MEMBERS` | `overlapping_member_ranges.zip` | `test_threat_22_overlapping_archive_members` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-23** | Multi-Disk ZIP Archives (Unsupported) | `SEC_MULTIDISK_ARCHIVE` | `multidisk_zip.zip` | `test_threat_23_multidisk_zip_unsupported` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-24** | ZIP64 Structure Exploits (Fail-Closed) | `SEC_ZIP64_UNSUPPORTED` | `zip64_unsupported.zip` | `test_threat_24_zip64_unsupported_fail_closed` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-25** | Oversized XML Part Size | `SEC_XML_PART_SIZE_LIMIT` | `oversized_xml_part.zip` | `test_threat_25_oversized_xml_part` | `PROCESSING_LIMIT_EXCEEDED` | 6 | 413 | **PASS** |
| **THREAT-26** | Excessive XML Depth (Stack Overflow) | `SEC_XML_DEPTH_LIMIT` | `deep_xml_nesting.zip` | `test_threat_26_excessive_xml_nesting_depth` | `PROCESSING_LIMIT_EXCEEDED` | 6 | 413 | **PASS** |
| **THREAT-27** | Excessive XML Elements (Billion Laughs) | `SEC_XML_ELEMENT_COUNT_LIMIT` | `xml_element_count_limit.zip` | `test_threat_27_excessive_xml_element_count` | `PROCESSING_LIMIT_EXCEEDED` | 6 | 413 | **PASS** |
| **THREAT-28** | XML DOCTYPE / DTD Processing | `SEC_XML_DOCTYPE` | `doctype_declaration.zip` | `test_threat_28_xml_doctype_declaration` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-29** | XXE: External Entity Resolution | `SEC_XML_XXE_SYSTEM` | `external_entity_xxe.zip` | `test_threat_29_xxe_external_entity` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-30** | XML Encoding Bypass (UTF-16/BOM) | `SEC_XML_DOCTYPE` | `utf16_doctype_bypass.zip` | `test_threat_30_xml_encoding_bypass_utf16_and_bom` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-31** | Malformed / Truncated XML Syntax | `SEC_XML_MALFORMED` | `malformed_xml_syntax.zip` | `test_threat_31_malformed_xml_syntax` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-32** | Hostile Input in `Pipeline.inspect` | `SEC_ZIPSLIP_PARENT` | `zipslip_parent.zip` | `test_threat_32_hostile_inspect` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-33** | Hostile Input in `clean(dry_run=True)` | `SEC_ZIPSLIP_PARENT` | `representative_zipslip.docx` | `test_threat_33_hostile_clean_dry_run` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-34** | Hostile Candidate in `verify()` | `SEC_ZIPSLIP_PARENT` | `representative_zipslip.docx` | `test_threat_34_hostile_verify_candidate` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-35** | Batch Processing Worker Isolation | `SEC_ZIPSLIP_PARENT` | `representative_zipslip.docx` | `test_threat_35_batch_processing_worker_isolation` | `INVALID_CONTAINER` | 0* | 200* | **PASS** |
| **THREAT-36** | Information Leakage in Diagnostics | Privacy Assertion | `secret_body.docx` | `test_threat_36_information_leakage_privacy` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |
| **THREAT-37** | Log / JSON Escape Injection | String Sanitization | (In-Memory String) | `test_threat_37_log_json_escape_injection` | N/A | 4 | 400 | **PASS** |
| **THREAT-38** | Premature Adapter Invocation | Adapter Isolation Spy | `representative_zipslip.docx` | `test_threat_38_premature_adapter_invocation_prevented` | `INVALID_CONTAINER` | 4 | 400 | **PASS** |

*\* Note on THREAT-35: Batch processor isolates faults per-item; overall batch returns exit 0 / HTTP 200 with individual item status set to `ERROR` and `summary.errors == 1`.*

---

## 7. Verification & Regression Provenance

### 7.1 Commit Provenance
- **Phase 9 Implementation Commit**: `73a5c24b47842c8e68e1a1fc40622db70eec3c0d`
- **Contract & Boundary Evidence Closure Commit**: `408b3e606e3949220a8e221c014378ac51a1a4c7`
- **ZIP-Descriptor & Evidence Closure Commit**: `73783182300e4b4a9e57758b2a1ae4a99a9cf236`
- **Historical Pre-Phase9 Baseline**: `1615 passed, 152 skipped, 0 failed, 0 warnings, 82.77s`

### 7.2 Frozen DOCX Verification
- `git diff v2.0.0 -- service/scripts/docx/`: **EMPTY (0 lines diff)**
- Golden DOCX Hash (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`):
  `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (**MATCH**)
- Candidate DOCX Hash (`04_CANDIDATE_LOSSLESS_OUTPUT.docx`):
  `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (**MATCH**)

### 7.3 Focused Phase 9 Suite
- Command: `uv run --with pytest python -m pytest tests/test_malformed_archives.py -ra`
- Result: **141 passed, 0 failed** in 1.30s

### 7.4 Format Regressions
- DOCX Body Carrier Suite ([`test_docx_body_carriers.py`](file:///tests/test_docx_body_carriers.py)): **49 passed**
- XLSX Lossless Suite ([`test_xlsx_lossless.py`](file:///tests/test_xlsx_lossless.py)): **40 passed**
- PPTX Lossless Suite ([`test_pptx_lossless.py`](file:///tests/test_pptx_lossless.py)): **46 passed**
- Total Format Regression: **135 passed, 0 failed** in 14.18s

### 7.5 Contract Regressions
- Command: `uv run --with pytest python -m pytest tests/test_cli_v21.py tests/test_api_v21.py tests/test_multi_format_revalidation.py tests/test_batch_processor.py tests/test_inspection_first.py tests/test_dry_run.py tests/test_capabilities_endpoint.py tests/test_ui_contract.py -ra`
- Result: **86 passed, 0 failed** in 11.32s

### 7.6 Canonical Final Full Suite Regression
- Command: `uv run --with pytest python -m pytest -ra`
- Result: **1759 passed, 152 skipped, 0 failed, 0 warnings in 103.82s**

---

## 8. Conclusion
Phase 9 satisfies all architectural, security, contract, and regression gates.
The declared Phase 9 hostile corpus is rejected under the configured SecurityLimits, with canonical public workflows protected before format-specific mutation.
Phase 9 is marked **PASS**. Phase 10 has NOT been started.
