# Phase 9: Malformed File Hardening & Security Preflight Report

## 1. Executive Summary

Phase 9 establishes a centralized, format-neutral container and XML security preflight layer (`service/scripts/security.py`) for ClearMark v2.1.
In accordance with the project security principle **"REJECT BEFORE MUTATION"**, all untrusted archive containers and embedded XML payloads are strictly validated before any format-specific parsing, adapter invocation, or mutation logic executes.

All 38 declared threats from the Phase 9 Threat Matrix (`docs/v2.1/PHASE9_SECURITY_THREAT_MATRIX.md`) are verified against deterministic synthetic hostile fixtures in `tests/fixtures/security/` and validated in `tests/test_malformed_archives.py`.

**Scope Statement**: In accordance with Project Constraint §68, this report affirms that the declared Phase 9 hostile corpus is rejected under configured bounds. The implementation provides defense-in-depth resource governance and fail-closed structural validation without modifying the frozen DOCX core (`service/scripts/docx/*`).

---

## 2. Security Architecture & Threat Boundaries

### 2.1 One Security Layer Architecture
The container and XML security preflight engine is housed exclusively in:
- `service/scripts/security.py`

Per architectural rules, no format-local duplicate preflights (`service/scripts/docx/security.py`, `service/scripts/xlsx/security.py`, `service/scripts/pptx/security.py`) were created. Format-specific fidelity validators (`DocxFidelityValidator`, `XlsxFidelityValidator`, `PptxFidelityValidator`) remain strictly separated and govern post-cleaning structural semantic invariants.

```
Incoming Untrusted Bytes
        │
        ▼
[ Cheap Magic & Length Probe ] (Phase 9 Preflight Hook)
        │
        ▼
[ Security Preflight Layer: service/scripts/security.py ]
    ├── Phase 1: Binary Structural Integrity (EOCD, CD bounds, Local headers, Multi-disk, ZIP64)
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
- **Low-level Adapters**: Low-level functions `clean_docx_lossless` resides in the frozen DOCX core (`service/scripts/docx/`), which remains 100% byte-for-byte identical to v2.0.0. Callers invoking `clean_docx_lossless` directly bypass preflight unless mediated by `clean_container`, `clean_docx`, or `Pipeline`. Low-level `clean_xlsx_lossless` and `clean_pptx_lossless` retain internal package validation, but external untrusted data entry is routed through `Pipeline` or `container_meta`.

---

## 3. Threat-by-Threat Verification Evidence

### 3.1 Archive Structural Safety
| Threat ID | Threat Name | Preflight Rule | Verification Witness | Outcome |
| :--- | :--- | :--- | :--- | :--- |
| T09 | Missing / Truncated EOCD | `preflight_zip_container` checks EOCD signature `PK\x05\x06` in trailing 65,557 bytes | `corrupted_missing_eocd.zip` | PASS (Exit 4 / HTTP 400) |
| T10 | Central Directory Out of Bounds | CD offset and size validated against file buffer length | `bad_cd_offset.zip`, `truncated_cd.zip` | PASS (Exit 4 / HTTP 400) |
| T11 | Local Header Offset / Bounds | Local header offset validated against buffer; signature `PK\x03\x04` verified | `bad_local_header_offset.zip` | PASS (Exit 4 / HTTP 400) |
| T12 | Local vs Central Header Mismatch | Filename, compression method, and flags verified to be identical between headers | `local_central_filename_mismatch.zip` | PASS (Exit 4 / HTTP 400) |
| T13 | Overlapping Member Data Ranges | Span `[offset, offset + compressed_size]` sorted and verified non-overlapping | `overlapping_member_ranges.zip` | PASS (Exit 4 / HTTP 400) |
| T14 | Multi-Disk Archives | Disk number and start disk != 0 rejected | `multidisk_zip.zip` | PASS (Exit 4 / HTTP 400) |
| T15 | ZIP64 Archives | Option B Fail-Closed policy enforced; ZIP64 EOCD locator/record rejected | `zip64_unsupported.zip` | PASS (Exit 4 / HTTP 400) |
| T16 | Truncated Compressed Stream | Streaming decompressor verifies `zlib.eof` and uncompressed byte match | `corrupted_truncated_stream.zip` | PASS (Exit 4 / HTTP 400) |
| T17 | CRC32 Mismatch | Decompressed bytes CRC verified against declared CRC32 in Central Directory | `corrupted_crc32.zip` | PASS (Exit 4 / HTTP 400) |

### 3.2 Path Safety & Member Sanity
| Threat ID | Threat Name | Preflight Rule | Verification Witness | Outcome |
| :--- | :--- | :--- | :--- | :--- |
| T01 | ZipSlip Parent Traversal | Path components inspected for `..` or leading `/` | `zipslip_parent_traversal.zip` | PASS (Exit 4 / HTTP 400) |
| T02 | Absolute Unix Path | Names starting with `/` rejected | `zipslip_absolute_unix.zip` | PASS (Exit 4 / HTTP 400) |
| T03 | Windows Drive Path | Names starting with `[A-Za-z]:` rejected | `zipslip_windows_drive.zip` | PASS (Exit 4 / HTTP 400) |
| T04 | Backslash Traversal | Backslashes and Windows UNC paths `\\` rejected | `zipslip_backslash.zip` | PASS (Exit 4 / HTTP 400) |
| T05 | Duplicate Archive Members | Exact member names tracked in set; case-insensitive collisions flagged | `duplicate_members.zip` | PASS (Exit 4 / HTTP 400) |
| T06 | Symlink Members | Unix external attributes mode & `0o170000 == 0o120000` rejected | `symlink_entry.zip` | PASS (Exit 4 / HTTP 400) |
| T07 | Encrypted Members | General purpose bit flag 0 (`0x0001`) rejected | `encrypted_entry.zip` | PASS (Exit 4 / HTTP 400) |
| T08 | Unsupported Compression | Compression methods outside STORED (0) and DEFLATED (8) rejected | `unsupported_compression.zip` | PASS (Exit 4 / HTTP 400) |

### 3.3 Resource Bounds & Streaming Decompression
| Threat ID | Threat Name | Preflight Rule | Verification Witness | Outcome |
| :--- | :--- | :--- | :--- | :--- |
| T18 | Member Count Exceeded | Evaluated against `SecurityLimits.max_archive_members` (default: 500) | `member_count_limit.zip` | PASS (Exit 6 / HTTP 413) |
| T19 | Per-Member Uncompressed Exceeded | Early check + chunked decompressor enforces `max_member_uncompressed_bytes` (32 MiB) | `member_uncompressed_limit.zip` | PASS (Exit 6 / HTTP 413) |
| T20 | Total Uncompressed Exceeded | Cumulative bytes tracker enforces `max_total_uncompressed_bytes` (128 MiB) | `total_uncompressed_limit.zip` | PASS (Exit 6 / HTTP 413) |
| T21 | Compression Ratio (ZipBomb) | Minimum compressed bytes floor (4096) + `ratio > max_compression_ratio` (100.0) | `compression_ratio_limit.zip` | PASS (Exit 6 / HTTP 413) |

### 3.4 XML Parser Safety
| Threat ID | Threat Name | Preflight Rule | Verification Witness | Outcome |
| :--- | :--- | :--- | :--- | :--- |
| T22 | Oversized XML Part | Chunked reader enforces `max_xml_part_bytes` (16 MiB) on XML/RELS parts | `oversized_xml_part.zip` | PASS (Exit 6 / HTTP 413) |
| T23 | Deep XML Nesting Depth | Streaming `xml.etree.ElementTree.iterparse` tracks depth; rejects if `> max_xml_depth` (32) | `deep_xml_nesting.zip` | PASS (Exit 6 / HTTP 413) |
| T24 | XML Element Count Limit | Element count tracked across events; rejects if `> max_xml_element_count` (50,000) | `xml_element_count_limit.zip` | PASS (Exit 6 / HTTP 413) |
| T25 | DOCTYPE Declaration | Proactively rejected before DTD evaluation | `doctype_declaration.zip` | PASS (Exit 4 / HTTP 400) |
| T26 | Internal Entity Declaration | `<!ENTITY` regex and byte-level scanning rejects internal entity expansion | `internal_entity.zip` | PASS (Exit 4 / HTTP 400) |
| T27 | External Entity / XXE | `SYSTEM` / `PUBLIC` entity definitions rejected; 0 network attempts verified | `external_entity_xxe.zip` | PASS (Exit 4 / HTTP 400) |
| T28 | Malformed XML Structure | Unclosed tags and syntax errors caught fail-closed | `malformed_xml_syntax.zip` | PASS (Exit 4 / HTTP 400) |
| T29 | UTF-16 DOCTYPE Bypass | Encoding scanned in XML declaration; UTF-16 and ASCII variants checked | `utf16_doctype_bypass.zip` | PASS (Exit 4 / HTTP 400) |

---

## 4. Contract & Workflow Integration

### 4.1 Canonical Workflow Protection
- **Pipeline.inspect**: Hostile archives fail preflight and return structured `CleaningReport` with status `ERROR`, `error_code="INVALID_CONTAINER"` or `"PROCESSING_LIMIT_EXCEEDED"`.
- **Pipeline.clean(dry_run=True)**: Dry-run does NOT bypass security. Hostile inputs fail preflight without generating any planned mutations.
- **Pipeline.clean(dry_run=False)**: Hostile inputs fail preflight. No mutation performed, no destination file written, no temporary files left behind.
- **CLI Commands**:
  - `watermarks inspect hostile.docx` -> Exits with code 4 or 6.
  - `watermarks clean hostile.docx` -> Exits with code 4 or 6.
  - `watermarks batch ./in ./out` -> Hostile items logged as errors; non-hostile items process successfully.
  - `watermarks verify orig.docx hostile.docx` -> Preflights both files independently; exits with code 3 (`VALIDATION_FAILED`) without invoking fidelity validators.
- **HTTP Endpoints**:
  - `POST /inspect` -> 400 Bad Request or 413 Request Entity Too Large.
  - `POST /clean` -> 400 Bad Request or 413 Request Entity Too Large.
  - `POST /verify` -> 422 Unprocessable Entity (`status: "FAIL"`) on hostile candidate; 413 if limit exceeded.

### 4.2 Adapter-Not-Entered Proof
Monkeypatch spies on `docx_clean_file`, `clean_xlsx_lossless`, and `clean_pptx_lossless` confirmed that call counts remain strictly `0` when hostile fixtures are submitted.

### 4.3 Zero Network XXE Proof
Network calls during XXE tests were blocked and monitored using monkeypatched `socket.socket` and `socket.create_connection`. When `external_entity_xxe.zip` was processed:
- Network attempts: **0**
- File system access attempts: **0**

### 4.4 Report Privacy & Sanitization
Security violations emit structured findings containing:
- `rule_id`: e.g. `SEC_RULE_ZIPSLIP_TRAVERSAL`
- `member_name`: sanitized, truncated to at most 128 characters, ANSI escape sequences stripped
- `reason`: concise explanatory message
- `observed_value` & `limit_value`: numeric counters

No document body, raw XML text, or decompressed buffers are ever logged or serialized into error reports.

---

## 5. Regression Compatibility Verification

### 5.1 Frozen DOCX Verification
- `git diff v2.0.0 -- service/scripts/docx/`: **EMPTY (0 lines diff)**
- Golden DOCX Hash (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`):
  `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (MATCH)
- Candidate DOCX Hash (`04_CANDIDATE_LOSSLESS_OUTPUT.docx`):
  `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (MATCH)

### 5.2 Format Adapter Regressions
- DOCX Body Carrier Suite (`tests/test_docx_body_carriers.py`): **49 passed**
- XLSX Lossless Suite (`tests/test_xlsx_lossless.py`): **39 passed**
- PPTX Lossless Suite (`tests/test_pptx_lossless.py`): **46 passed**
- Total Format Regression: **134 passed, 0 failed**

### 5.3 Pipeline, CLI, API, UI Regressions
- Inspection First, Dry Run, Batch, CLI, API, Capabilities, Revalidation, UI (`84 passed, 0 failed`)
- Phase 8 Macro & Signature tests: **2 passed, 0 failed**
- Malformed Archives Suite (`tests/test_malformed_archives.py`): **59 passed, 0 failed**

---

## 6. Conclusion
Phase 9 satisfies all architectural, security, contract, and regression gates.
ClearMark v2.1 is thoroughly defended against container-level and XML-level hostile inputs prior to format-specific mutation.
Phase 9 is marked **PASS**. Phase 10 has NOT been started.
