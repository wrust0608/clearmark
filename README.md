# ClearMark

ClearMark is a high-fidelity, stdlib-first Python service and CLI tool designed to inspect and scrub supported AI provenance carriers, metadata markers, and covert Unicode watermarks from documents and media files.

ClearMark operates under an **inspection-first**, **security-bounded**, and **privacy-preserving** architecture. It prioritizes document structure preservation over destructive re-serialization, ensuring untouched package parts, formulas, styles, and layouts remain intact.

---

## What ClearMark Does and Does Not Do

### Supported Capabilities
- **Scrubs Supported Metadata & Provenance Carriers**: Removes known provenance metadata structures (e.g. standard EXIF, XMP, IPTC tags, C2PA/JUMBF manifests, and document properties) across 23 canonical format policies.
- **Removes Covert Unicode Watermarks While Preserving Contextual Joiners**: Removes supported invisible-character carriers while preserving contextually legitimate joiners such as emoji ZWJ sequences (e.g. compound emojis) and Arabic/Persian/Devanagari shaping characters. Normalizes homoglyphs in supported text formats.
- **Preserves Document Invariants (OOXML)**: Employs minimal targeted patching for DOCX, XLSX, and PPTX files. Untouched parts are passed through byte-for-byte (`LEVEL_A` raw OPC preservation).
- **Two-File Fidelity Verification**: Provides executable fidelity verification for DOCX, XLSX, and PPTX candidate files against original sources.

### Non-Guarantees & Bounded Scope
- **Does NOT Guarantee Universal Watermark Removal**: ClearMark inspects and removes only supported, configured provenance carriers. It cannot detect or scrub arbitrary proprietary, encrypted, or unknown statistical watermarking schemes.
- **Does NOT Cryptographically Validate C2PA Signatures**: ClearMark detects and strips C2PA metadata manifests; it does not validate cryptographic certificate trust chains.
- **Does NOT Claim Lossless Raster Inpainting**: Inpainting pixel watermarks in `balanced` or `aggressive` modes modifies image pixel data.
- **Fail-Closed on Unrecognized Structures**: Hostile archives (ZipSlip, decompression bombs exceeding 100x ratio), XML bombs (XXE, depth > 100), and ZIP64 extensions are rejected in preflight before mutation.

For detailed format-by-format guarantees, consult the [Format Guarantees Specification](docs/format_guarantees.md).

---

## Quick Start

ClearMark requires Python 3.10+ and standard library modules for core operations.

### 1. Inspect a File (Read-Only)
Inspection reports detected carriers without mutating disk contents:

```powershell
# PowerShell
python -m service.scripts.cli inspect input.docx --json
```

```bash
# Bash
watermarks inspect input.docx --json
```

### 2. Preview Planned Changes (Dry-Run)
Dry-run executes in-memory planning and validation with zero writes to disk:

```powershell
# PowerShell
watermarks clean input.docx --dry-run --json
```

### 3. Clean a File
Apply authorized mutations using default `safe` mode and write to a destination:

```powershell
# PowerShell
watermarks clean input.docx -o output.cleaned.docx
```

### 4. Verify Document Invariants
Validate that non-target document structures and visible text remain intact:

```powershell
# PowerShell
watermarks verify input.docx output.cleaned.docx --json
```

---

## Important Status Terminology

To ensure transparent reporting, ClearMark strictly differentiates between detection states and operational outcomes:

| Status Token | Category | Meaning |
|:---|:---|:---|
| `DETECTED` | Detection | A supported watermark or provenance carrier was inspected and positively found. |
| `NOT_DETECTED` | Detection | The specific checked surface was inspected, and no supported carrier was found. |
| `NOT_CHECKED` | Detection | The surface was intentionally not inspected (e.g. to avoid altering complex structures). Does **not** mean the surface is clean. |
| `UNAVAILABLE` | Detection | The inspection engine requires an optional external dependency that is missing. |
| `UNSUPPORTED` | Detection | The format or sub-structure has no defined inspection policy. |
| `INSPECTED` | Outcome | Read-only inspection completed successfully. |
| `NO_CHANGE_REQUIRED` | Outcome | All checked surfaces contained no recognized carriers. Does **not** mean all conceivable watermarks are absent. |
| `CLEANED` | Outcome | Planned mutations were applied and passed post-clean invariant checks. |
| `VALIDATION_FAILED` | Outcome | Post-clean verification failed; mutations were rolled back; original file is untouched. |
| `DEPENDENCY_MISSING` | Outcome | Operation halted because a required external tool is not installed. |
| `LIMIT_EXCEEDED` | Outcome | File or container exceeded configured resource or size bounds. |

---

## CLI Command Reference

The command-line interface provides five subcommands:

### `watermarks inspect`
Inspect a file for supported provenance carriers (read-only):
```bash
watermarks inspect <file> [--mode {safe,balanced,aggressive}] [--json]
```

### `watermarks clean`
Clean supported provenance carriers from a file:
```bash
watermarks clean <file> [-o <output>] [--in-place] [--dry-run] [--mode {safe,balanced,aggressive}] [--json]
```
- `--dry-run`: Previews planned mutations in memory without modifying the input or writing output.
- `--in-place`: Atomically replaces the input file upon validation success.
- `--mode`: Processing mode (default: `safe`). `safe` prefers preservation when confidence is insufficient.

### `watermarks batch`
Batch process multiple files or directories with per-file failure isolation:
```bash
watermarks batch <inputs...> [-o <output-dir>] [--reports-dir <reports-dir>] [-r] [--dry-run] [--mode {safe,balanced,aggressive}] [--json]
```
- Fault Isolation: A failure on one file does not halt processing of remaining items.
- Safety: Excludes nested output/report directories and rejects same-root output targets. Does not follow symlinks or junction points.

### `watermarks verify`
Verify structural invariants and text equality between original and candidate files:
```bash
watermarks verify <original> <candidate> [--json]
```
*Supported for DOCX, XLSX, and PPTX formats.*

### `watermarks capabilities`
Query the runtime capability matrix and local environment state:
```bash
watermarks capabilities [--json]
```

> [!NOTE]
> When `--json` is supplied, structured JSON is written to `stdout`, while human progress diagnostics are routed to `stderr`.

---

## CLI Exit Codes

ClearMark uses unambiguous exit codes across single-file and batch modes:

| Code | Symbol | Meaning |
|:---|:---|:---|
| **0** | `SUCCESS` | File cleaned successfully, or inspection/dry-run found no change required. |
| **2** | `UNSUPPORTED` | Format or container type is unsupported. (Strictly reserved for format routing). |
| **3** | `VALIDATION_FAILED` | Post-clean invariant check failed; file was rolled back. |
| **4** | `INVALID_INPUT` | Missing input, zero inputs found, or invalid configuration. |
| **5** | `DEPENDENCY_MISSING` | Required external system tool (e.g. ghostscript) is missing. |
| **6** | `LIMIT_EXCEEDED` | File size, batch count, aggregate size, or archive limit exceeded. |
| **7** | `BATCH_PARTIAL_FAILURE` | Batch operation completed with mixed results (some files succeeded, others failed). |
| **10** | `INTERNAL_ERROR` | Unhandled exception or internal system error. |

---

## Resource & Processing Limits

To protect system stability, ClearMark enforces deterministic resource bounds:

| Scope | Limit | Enforcement Source |
|:---|:---|:---|
| **Single File Input** | `256 MiB` | `common.MAX_INPUT_BYTES` |
| **CLI Stdin Stream** | `64 MiB` | `common.MAX_STDIN_BYTES` |
| **HTTP Request Body** | `384 MiB` | `server.MAX_BODY_BYTES` |
| **HTTP Input Payload** | `256 MiB` | `server.MAX_INPUT_BYTES` |
| **Batch Single-File** | `32 MiB` | `batch_processor.MAX_INPUT_BYTES` |
| **Batch Aggregate Size** | `200 MiB` | `batch_processor.MAX_BATCH_TOTAL_BYTES` |
| **CLI Batch Item Count** | `100` files | `batch_processor.MAX_BATCH_FILES` |
| **HTTP /batch Request Item Count** | `50` files | `server.MAX_BATCH_FILES` |
| **Archive Decompression Ratio**| `100x` | `security.SecurityLimits.max_compression_ratio` |
| **ZIP Member Uncompressed** | `64 MiB` | `security.SecurityLimits.max_member_uncompressed_bytes` |
| **ZIP Total Uncompressed** | `128 MiB` | `security.SecurityLimits.max_total_uncompressed_bytes` |
| **ZIP Member Count** | `10,000` | `security.SecurityLimits.max_member_count` |
| **XML Max Part Size** | `32 MiB` | `security.SecurityLimits.max_xml_part_bytes` |
| **XML Max Total Size** | `128 MiB` | `security.SecurityLimits.max_total_xml_bytes` |
| **XML Max Nesting Depth** | `100` | `security.SecurityLimits.max_xml_depth` |
| **XML Max Elements** | `500,000` | `security.SecurityLimits.max_xml_elements` |

---

## HTTP Service API

ClearMark includes a stdlib-based HTTP service designed for local integration (`http://localhost:8765`).

### Start the Server
```bash
python -m service.scripts.server --port 8765
```

### Endpoints
- **`GET /capabilities`**: Returns runtime-detected format policies and available tools.
- **`POST /inspect`**: Inspects a base64-encoded file payload (returns diagnostic report).
- **`POST /clean`**: Cleans a base64-encoded file payload (returns cleaned file + report).
- **`POST /verify`**: Verifies original vs candidate base64 payloads (returns invariant check outcome).
- **`POST /batch`**: Processes up to 50 files in a single request with per-file failure isolation.

### HTTP Status Code Mapping
The HTTP API maps internal pipeline error codes directly to standard status codes:
- **`200 OK`**: Operation succeeded.
- **`400 Bad Request`**: Malformed or truncated container (`INVALID_CONTAINER`).
- **`413 Payload Too Large`**: Request body or payload exceeds size limit (`PROCESSING_LIMIT_EXCEEDED`).
- **`415 Unsupported Media Type`**: Format is not supported (`UNSUPPORTED_FORMAT`).
- **`422 Unprocessable Entity`**: Invariant validation failed or archive feature rejected (`VALIDATION_FAILED`, `UNSUPPORTED_ARCHIVE_FEATURE`).
- **`424 Failed Dependency`**: Required optional external dependency is missing (`OPTIONAL_DEPENDENCY_MISSING`).
- **`500 Internal Server Error`**: Unexpected internal server fault (`INTERNAL_ERROR`).

---

## Performance & Memory Caveats

ClearMark processes document and archive buffers entirely in-memory to guarantee atomic rollbacks and prevent partial writes:
- **Peak Memory**: Cleaning a 100 MiB document can require hundreds of megabytes to approximately 1.1 GiB of transient process memory.
- **Throughput**: Performance is format-dependent. Structured archive parsing (e.g. DOCX) is fast on modern hosts, whereas large plain-text regex scanning is computationally intensive (~0.08 MiB/s measured for large text files on benchmark systems).
- **Batching**: Individual batch inputs are capped at 32 MiB each (200 MiB total aggregate) to maintain bounded process memory.

For full benchmark measurements and hardware profiles, see the [Phase 11 Performance Report](docs/v2.1/PHASE11_PERFORMANCE_REPORT.md).

---

## Detailed Specifications

- [Format Capabilities Matrix](docs/capabilities.md): Exhaustive 23-policy runtime specification.
- [Format Guarantees Specification](docs/format_guarantees.md): Structural, semantic, and invariant preservation rules.
- [Phase 11 Performance Evidence](docs/v2.1/PHASE11_PERFORMANCE_REPORT.md): Empirical scaling benchmarks and memory profiling.
- [Phase 10 Idempotence Evidence](docs/v2.1/PHASE10_IDEMPOTENCE_REPORT.md): Mathematical fixed-point proofs ($C(C(x)) == C(x)$).
