# ClearMark v2.1 Phase 9 — Security Threat Matrix

## Executive Summary

Phase 9 establishes a centralized, format-neutral preflight and resource-governance security layer (`service/scripts/security.py`) for untrusted containers and hostile XML payloads.

This document audits all known container and XML threat vectors, classifies their pre-Phase 9 status across the codebase, and defines the unified post-Phase 9 target enforcement in `service/scripts/security.py`.

### Threat Classification Taxonomy
- **`ALREADY_BLOCKED`**: Comprehensively detected and rejected across all entry points prior to Phase 9.
- **`PARTIALLY_BLOCKED`**: Detected in some scenarios (e.g. only via declared metadata or after full central directory parsing) but vulnerable to streaming expansion, forged headers, or edge cases.
- **`FORMAT_LOCAL_ONLY`**: Implemented inside specific format adapters (e.g., `xlsx/package.py` or `pptx/package.py`) but missing from universal pipeline preflight, leaving other formats or early probes vulnerable.
- **`NOT_BLOCKED`**: No pre-Phase 9 detection or enforcement; would execute unconstrained or cause parser crash/resource exhaustion.
- **`NOT_APPLICABLE`**: Threat does not apply to the target file formats or execution model.

---

## Comprehensive Threat Audit

| Threat ID | Threat Category / Vector | Pre-Phase 9 Classification | Pre-Phase 9 Location & Gaps | Phase 9 Unified Target Enforcement (`security.py`) |
| :--- | :--- | :--- | :--- | :--- |
| **THREAT-01** | **ZipSlip: Relative Directory Traversal (`../evil.xml`)** | `FORMAT_LOCAL_ONLY` | Blocked locally in `docx/package.py`, `xlsx/package.py`, `pptx/package.py`. Not enforced during initial format sniffing or container dispatch. | Strict path validator rejecting any `..` component before package unpacking or dispatch. |
| **THREAT-02** | **ZipSlip: Absolute Unix Path (`/etc/passwd`, `/evil.xml`)** | `FORMAT_LOCAL_ONLY` | Blocked locally in format adapters. Format detection and early probes did not guard. | Rejected immediately during Central Directory record parsing. |
| **THREAT-03** | **ZipSlip: Windows Drive Letter (`C:\evil.xml`, `C:/evil.xml`)** | `PARTIALLY_BLOCKED` | `os.path.isabs()` in some packages, but drive letters with relative slashes or Windows quirks could slip through on non-Windows hosts. | Strict regex/path validation checking for drive letters (`^[a-zA-Z]:`). |
| **THREAT-04** | **ZipSlip: Backslash Traversal (`folder\..\evil.xml`)** | `PARTIALLY_BLOCKED` | Python `zipfile` on POSIX may treat backslash as literal character in filename; normalization in format adapters varied. | Explicit rejection of any `\` backslash in member names. |
| **THREAT-05** | **ZipSlip: UNC Paths (`\\server\share\evil`)** | `NOT_BLOCKED` | UNC paths were not explicitly recognized as illegal in OPC containers. | Rejected immediately if path starts with `//` or `\\`. |
| **THREAT-06** | **ZipSlip: NUL Byte Injection (`evil.xml\0.txt`)** | `NOT_BLOCKED` | Not checked in Central Directory or Local File Headers. | Reject member names containing `\x00`. |
| **THREAT-07** | **Duplicate ZIP Member Names (Exact)** | `FORMAT_LOCAL_ONLY` | Checked in `xlsx/package.py` and `pptx/package.py`. Standard `zipfile` allows duplicate entries (last entry wins). | Strict member name uniqueness enforcement in Central Directory. Duplicate fails closed. |
| **THREAT-08** | **Non-canonical Collisions (`a//b`, `a/./b`)** | `NOT_BLOCKED` | Parsers could normalize differently or access unintended entries. | Rejection of non-canonical OPC paths containing empty segments (`//`) or current-dir (`/./`). |
| **THREAT-09** | **ZIP Symlink Entries (`S_IFLNK`)** | `NOT_BLOCKED` | Unix external attributes (`external_attr >> 16`) were not inspected. | Reject any member with Unix mode `S_IFLNK`. OPC packages require no symlinks. |
| **THREAT-10** | **Encrypted ZIP Members** | `FORMAT_LOCAL_ONLY` | Checked in `xlsx/package.py` and `pptx/package.py`. In generic container helpers, encrypted files raised `RuntimeError` or prompted for password. | Reject any member with general-purpose flag bit 0 set (`flags & 0x01`). Zero password prompting. |
| **THREAT-11** | **Unsupported Compression Methods** | `FORMAT_LOCAL_ONLY` | `xlsx/package.py` verified Store/Deflate during rebuild, but container detection did not validate compression methods upfront. | Strict allowlist: `STORED` (0) and `DEFLATED` (8) only. Any other method fails closed. |
| **THREAT-12** | **Archive Member Count Bomb** | `FORMAT_LOCAL_ONLY` | Capped at 10,000 in format adapters, but initial `detect_container_format` ran unconstrained `zipfile.ZipFile.namelist()`. | Central Directory parser enforces `max_member_count` (default: `10,000`) before processing member contents. |
| **THREAT-13** | **Single-Member Uncompressed Size Bomb** | `PARTIALLY_BLOCKED` | `container_meta.py` checked `ZipInfo.file_size`, but forged metadata could declare 0 bytes and expand infinitely. | Streaming chunked decompression aborts the instant decompressed bytes exceed `max_member_uncompressed_bytes` (default: `67,108,864` B / 64 MiB). |
| **THREAT-14** | **Total Uncompressed Size Bomb (Cumulative)** | `PARTIALLY_BLOCKED` | Handled via declared `file_size` summation in adapters, and chunked budget in `_read_zip_member`, but not unified or applied to all public pipelines. | Strict cumulative streaming counter across all decompressed members enforces `max_total_uncompressed_bytes` (default: `134,217,728` B / 128 MiB). |
| **THREAT-15** | **ZipBomb Compression Amplification Ratio** | `FORMAT_LOCAL_ONLY` | `pptx/package.py` had a ratio check; `docx` and `xlsx` did not. | Unified compression ratio check (`uncompressed / effective_comp <= max_compression_ratio`, default: `100.0`) with `min_compressed_bytes_for_ratio` (default: `1,024` B) floor. |
| **THREAT-16** | **Forged Metadata / Decompression Discrepancy** | `NOT_BLOCKED` | Trusting `ZipInfo.file_size` allowed attackers to conceal huge payloads. | Decompression is strictly streaming and bounds-checked. Actual output bytes govern limits. |
| **THREAT-17** | **CRC32 Mismatch / Corrupted Deflate Stream** | `FORMAT_LOCAL_ONLY` | Checked during `xlsx` rebuild, but not verified uniformly in `inspect` or `dry_run` pipelines. | Decompression validates CRC32 and catches truncated/corrupt deflate streams. |
| **THREAT-18** | **Missing / Truncated EOCD Record** | `PARTIALLY_BLOCKED` | Standard `zipfile` raises `BadZipFile`, but raw parsers in format adapters had varying fallback behavior. | Strict EOCD validation: search last 65 KiB, verify signature, verify minimum 22 bytes, check comment length bounds. |
| **THREAT-19** | **Central Directory Offset / Size Out of Bounds** | `FORMAT_LOCAL_ONLY` | Checked partially in format adapters. | Strict boundary verification: `cd_offset + cd_size <= eocd_offset` and within total archive bytes. |
| **THREAT-20** | **Local File Header Out of Bounds** | `FORMAT_LOCAL_ONLY` | Checked in `xlsx` and `pptx` during raw parsing. | Binary preflight verifies every `local_header_offset + 30 + nlen + elen + csize` lies within archive bounds. |
| **THREAT-21** | **Local vs Central Directory Mismatch** | `NOT_BLOCKED` | Attackers can hide malicious files or alter filenames between Local Header and Central Directory to fool different parsers. | Full consistency check: filename, compression method, and flags must match between CD and Local Header. |
| **THREAT-22** | **Overlapping Archive Member Ranges** | `NOT_BLOCKED` | Attackers craft archives where multiple members share byte slices, inducing parser confusion. | Range collision detection: sort member physical `[lhoff, lhoff + 30 + nlen + elen + csize]` ranges and assert no overlap. |
| **THREAT-23** | **Multi-Disk ZIP Archives** | `FORMAT_LOCAL_ONLY` | Checked in `xlsx/package.py`. | EOCD disk numbers (`disk_num == 0` and `cd_disk == 0`) strictly enforced. |
| **THREAT-24** | **ZIP64 Structure Exploits** | `NOT_BLOCKED` | Python `zipfile` partially supports ZIP64, which could allow massive offsets or unexpected parser states. | **Option B (Fail-Closed)**: Reject any ZIP64 structures (locator `PK\x06\x07`, record `PK\x06\x06`, `0xFFFF`/`0xFFFFFFFF` markers, or extra field ID `0x0001`). |
| **THREAT-25** | **Oversized XML Part Size** | `NOT_BLOCKED` | No XML-specific part size limit existed prior to parsing. | Reject any XML part whose uncompressed size exceeds `max_xml_part_bytes` (default: `33,554,432` B / 32 MiB). |
| **THREAT-26** | **Excessive XML Nesting Depth (Stack Overflow)** | `NOT_BLOCKED` | Recursive XML processing or standard DOM parsers could crash CPython stack on 10,000+ nested `<node>`. | Streaming expat parser tracks nesting depth; aborts if `depth > max_xml_depth` (default: `100`). |
| **THREAT-27** | **Excessive XML Element Count (Billion Laughs)** | `NOT_BLOCKED` | No element count limit existed prior to AST parsing. | Streaming expat parser tracks start elements; aborts if `count > max_xml_elements` (default: `500,000`). |
| **THREAT-28** | **XML DOCTYPE / DTD Processing** | `PARTIALLY_BLOCKED` | `defusedxml` is used in some parts, but raw `xml.etree` or regex was used elsewhere. | Reject any XML part containing `<!DOCTYPE` or `<!ENTITY` upfront before XML parsing. |
| **THREAT-29** | **XXE: External SYSTEM / PUBLIC Entity Resolution** | `PARTIALLY_BLOCKED` | Relied on default stdlib parser settings which might attempt local resolution or throw generic errors. | Zero network & zero disk resolution: upfront declaration rejection; verified by monkeypatching network sockets to 0 attempts. |
| **THREAT-30** | **XML Encoding Bypass (e.g. UTF-16 DOCTYPE)** | `NOT_BLOCKED` | Byte scanning for `b"<!DOCTYPE"` in ASCII/UTF-8 misses UTF-16 LE/BE encoded DOCTYPE declarations (`b"<\x00!\x00D\x00..."`). | Encoding-aware declaration scanner supporting UTF-8, UTF-16-LE, UTF-16-BE, and ISO-8859-1. |
| **THREAT-31** | **Malformed / Truncated XML Syntax** | `ALREADY_BLOCKED` | Standard parsers raised `ParseError`, but error was sometimes unhandled or mapped to 500 instead of 400/Exit 4. | Structured rejection as `ErrorCode.INVALID_CONTAINER` (Exit 4, HTTP 400). |
| **THREAT-32** | **Hostile Input in `Pipeline.inspect`** | `NOT_BLOCKED` | `inspect` parsed containers without mutation, but was vulnerable to decompression bombs and deep XML. | Preflight runs identically in `inspect()`. |
| **THREAT-33** | **Hostile Input in `Pipeline.clean(dry_run=True)`** | `NOT_BLOCKED` | Dry run could bypass full validation in some code paths. | Preflight runs identically in `dry_run=True`. Dry run is not an exemption. |
| **THREAT-34** | **Hostile Candidate in `verify(original, candidate)`** | `NOT_BLOCKED` | Fidelity validators assumed candidate was a well-formed archive. | Both original and candidate are independently preflighted before fidelity validators run. |
| **THREAT-35** | **Batch Processing Worker Crash** | `PARTIALLY_BLOCKED` | Uncaught zip bomb or memory error could terminate batch worker process. | Per-item fault isolation: item fails with structured error, siblings continue processing cleanly. |
| **THREAT-36** | **Information Leakage in Security Diagnostics** | `PARTIALLY_BLOCKED` | Error messages could print snippet of malformed XML or hostile file contents. | Security findings are strictly metadata-only (rule ID, member name, numeric values). Zero payload content dumped. |
| **THREAT-37** | **Log / JSON Escape Sequence Injection** | `NOT_BLOCKED` | Member names containing ANSI escape codes or control characters could disrupt terminal or logging. | Sanitization function strips control characters and escapes quotes/newlines before reporting. |
| **THREAT-38** | **Premature Format-Specific Adapter Invocation** | `NOT_BLOCKED` | Format detection dispatched directly to `DocxPackage`, `XlsxPackage`, or `PptxPackage` before container safety was proven. | Preflight runs before any format adapter is instantiated. Format adapter is never entered on hostile inputs. |

---

## Authoritative Limits Reference (`SecurityLimits`)

The class [`SecurityLimits`](file:///service/scripts/security.py#L69-L116) in `service/scripts/security.py` is the **single runtime source of truth** for all limits. Markdown documentation must reflect these exact defaults; if numeric defaults are adjusted in code, runtime `SecurityLimits` is authoritative.

```python
max_member_count: int = 10000
max_member_uncompressed_bytes: int = 64 * 1024 * 1024  # 64 MiB
max_total_uncompressed_bytes: int = 128 * 1024 * 1024  # 128 MiB
max_compression_ratio: float = 100.0
min_compressed_bytes_for_ratio: int = 1024
max_member_name_bytes: int = 1024
max_xml_part_bytes: int = 32 * 1024 * 1024  # 32 MiB
max_total_xml_bytes: int = 128 * 1024 * 1024  # 128 MiB
max_xml_depth: int = 100
max_xml_elements: int = 500000
chunk_size: int = 64 * 1024  # 64 KiB
```

---

## Architectural Principles Enforced

1. **Single Universal Security Gate**: `service/scripts/security.py` is the sole preflight authority.
2. **Frozen Core Preservation**: `service/scripts/docx/` remains 100% frozen. No imports or changes inside `docx/`.
3. **Fail-Closed Default**: Any ambiguous structure, unsupported feature, or limit breach fails immediately.
4. **Zero-Mutation Preflight**: Preflight never writes files, alters archives, or normalizes filenames.
5. **Deterministic Public Contract**: Exit code 4 for malformed containers, Exit code 6 for resource limits; HTTP 400 for malformed containers, HTTP 413 for resource limits; Exit code 3 / HTTP 422 for post-preflight fidelity validation failures.
