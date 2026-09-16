# ClearMark v2.1 Phase 4 Report — Batch Processing Engine

> **Phase**: Phase 4 (Batch Processing Engine)  
> **Status**: PASS  
> **Canonical Pre-Phase 4 Baseline**: Commit `6e5a5be600a69831c094db7a4941f1b4678c0919` (1431 passed, 152 skipped, 0 failed, 0 warnings in 74.27s)  
> **Canonical Final Full Pytest**: 1463 passed, 152 skipped, 0 failed, 0 warnings in 84.19s  
> **Frozen Core**: Lossless DOCX Subsystem (`service/scripts/docx/`)  
> **Golden DOCX SHA256**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d`  
> **Candidate DOCX SHA256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297`  

---

## 1. Executive Summary

Phase 4 introduces a resilient, isolated batch processing engine for ClearMark v2.1:
1. **Batch Processor Abstraction (`service/scripts/batch_processor.py`)**: Centralized `BatchProcessor` orchestrating multiple explicit files or directory trees while strictly reusing the canonical `Pipeline` (`Pipeline.clean`, `Pipeline.inspect`). Zero duplication of format adapters, inspection, policy, or validation.
2. **File-Level Failure Isolation**: One corrupt, malformed, or unsupported file never aborts or poisons sibling files in the batch. Each file runs within an isolated boundary with fresh state.
3. **Deterministic Ordering**: Explicit arguments preserve exact user order. Directory discovery applies stable lexical sorting on normalized relative paths. `BatchReport.items` strictly mirrors execution order.
4. **Collision-Safe Outputs & Original Overwrite Protection**: Batch processing never overwrites input originals. Directory structures are preserved under `--output-dir`. Output collisions are deterministically suffixed (`.cleaned.ext`, `.cleaned.1.ext`). Pre-existing outputs are preserved.
5. **Strict Metadata-Only Report Model**: `BatchReport` and `BatchItemResult` serialize strictly metadata, hashes, timings, format, status, and safe error codes. Cleaned file bytes/base64 are **never** part of the canonical `BatchReport` schema.
6. **Explicit HTTP Transport Envelope**: `POST /batch` separates canonical metadata report from file delivery payload:
   `{"ok": true, "report": {...}, "outputs_included": bool, "output_delivery": str, "outputs": [...]}`.
7. **Response Memory Safety & Inline Limits**: Defined `WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES` (default: 32 MiB), strictly distinct from `WATERMARKS_MAX_BATCH_TOTAL_BYTES` (default: 200 MiB). Raw output size is evaluated *before* base64 encoding to prevent 6x+ memory amplification.
8. **Mathematical Reconciliation Invariant**: `sum(terminal categories) == total` is strictly enforced across all runs.
9. **Zero-Output Invariant for Failed/Dry-Run Items**: Failed, unsupported, or dry-run files write zero files to the output directory and yield zero entries in HTTP `outputs`.
10. **Canonical CLI Command (`watermarks batch`)**: Full CLI command supporting `-o/--output-dir`, `--reports-dir`, `--mode`, `--dry-run`, `-r/--recursive`, and `--json` (metadata-only on `stdout`).
11. **Zero-Network & Privacy Invariant**: 0 network egress during local batch processing. Canonical reports contain metadata only; document body text dumps are strictly forbidden.

---

## 2. Architectural Guarantees & Invariants

### A. Failure Isolation
- Every item in a batch is processed within its own item-level `try/except` boundary.
- If item $i$ encounters an error (e.g. `INVALID_CONTAINER`, `FILE_NOT_FOUND`, `UNSUPPORTED`), it records the failure in `BatchItemResult` and increments `summary.errors` or `summary.unsupported`.
- Processing continues seamlessly for item $i+1 \dots N$.
- Partial success is not global failure: successful outputs remain committed and available on disk.

### B. Deterministic Ordering
- **Explicit Inputs**: If inputs are provided as explicit file arguments (`watermarks batch c.txt a.docx b.png`), the items are processed in exact argument order: `c.txt`, `a.docx`, `b.png`.
- **Directory Discovery**: When a directory path is supplied, files are discovered non-recursively (or recursively with `-r/--recursive`) and sorted lexically by their normalized relative path (`str(rel_path).replace("\\", "/")`).
- **Symlink Invariant**: Symlinks are never followed during directory discovery or explicit file processing to prevent path traversal loops and unsafe out-of-tree dereferencing.

### C. Output Collision Safety Policy
- **Original Overwrite Protection**: Batch outputs are never written directly over the original input path unless explicitly designed in future phases.
- **Directory Batches**: Preserve relative directory structure under `--output-dir`. For example, `dir1/report.docx` -> `<out>/dir1/report.cleaned.docx`.
- **Name Collisions**: When multiple files share the same target basename or pre-existing files reside in the output directory, collision-safe suffixes are appended:
  - `<stem>.cleaned.<ext>`
  - `<stem>.cleaned.1.<ext>`
  - `<stem>.cleaned.2.<ext>`
- **No Output on Failure**: Items categorized as `ERROR`, `UNSUPPORTED`, `VALIDATION_FAILED`, or executed in `dry_run` mode write **zero** output files to disk. Temporary files are removed immediately upon failure.

### D. Honest Summary & Mathematical Reconciliation
- The `BatchSummary` model tracks terminal outcomes:
  - `cleaned`: Files where high-confidence watermarks/metadata were removed.
  - `no_change`: Files where no watermark or carrier was detected.
  - `inspected`: Files processed under `dry_run` or `inspect` operations.
  - `unsupported`: Files whose format or container features are not supported.
  - `validation_failed`: Files where post-cleaning invariants failed.
  - `errors`: Files with container errors, missing files, or processing failures.
  - `skipped`: Files skipped due to fatal container constraints.
- **Reconciliation Invariant**:
  $$\text{cleaned} + \text{no\_change} + \text{inspected} + \text{unsupported} + \text{validation\_failed} + \text{errors} + \text{skipped} \equiv \text{total}$$
- **Dry-Run Representation**: In `--dry-run`, items are categorized under `inspected`, `would_change` is set to `true`, and `changed` is `false`. Previewed mutations are never falsely classified as `cleaned`.

---

## 3. Data Models (`service/scripts/batch_processor.py`)

### `BatchItemResult` (Metadata-Only Model)
```python
@dataclass
class BatchItemResult:
    index: int
    input_path: str
    input_sha256: Optional[str] = None
    format: str = "unknown"
    status: str = "INSPECTED"  # CLEANED, NO_CHANGE_REQUIRED, ERROR, etc.
    output_path: Optional[str] = None
    cleaned_bytes: Optional[bytes] = None  # Transient runtime state only
    report: Optional[dict[str, Any]] = None  # Canonical CleaningReport
    error_code: Optional[str] = None
    error_message_safe: Optional[str] = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to canonical metadata-only dictionary.
        Invariant: cleaned_bytes is transient runtime state only and is strictly
        excluded from the canonical report model."""
        return {
            "index": self.index,
            "input_path": self.input_path,
            "input_sha256": self.input_sha256,
            "format": self.format,
            "status": self.status,
            "output_path": self.output_path,
            "error_code": self.error_code,
            "error_message_safe": self.error_message_safe,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "report": self.report,
        }
```

### `BatchSummary`
```python
@dataclass
class BatchSummary:
    total: int = 0
    cleaned: int = 0
    no_change: int = 0
    inspected: int = 0
    unsupported: int = 0
    validation_failed: int = 0
    errors: int = 0
    skipped: int = 0

    def reconcile(self) -> bool:
        return (self.cleaned + self.no_change + self.inspected +
                self.unsupported + self.validation_failed +
                self.errors + self.skipped) == self.total
```

### `BatchReport` (Metadata-Only Model)
```python
@dataclass
class BatchReport:
    batch_id: str
    started_at: str
    finished_at: str
    mode: str
    dry_run: bool
    input_count: int
    items: list[BatchItemResult]
    summary: BatchSummary
    privacy: dict[str, Any]
    performance_elapsed_ms: float
    schema_version: str = "2.1.0"
    operation: str = "clean"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "operation": self.operation,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_count": self.input_count,
            "summary": self.summary.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "privacy": self.privacy,
            "performance": {"elapsed_ms": round(self.performance_elapsed_ms, 2)},
        }
```

---

## 4. Canonical CLI: `watermarks batch`

### Command Syntax
```bash
watermarks batch <inputs...> [OPTIONS]
```

### Options
- `<inputs...>`: One or more explicit file paths or directory paths.
- `-o, --output-dir <dir>`: Directory where cleaned files are saved.
- `--reports-dir <dir>`: Directory where individual per-file reports (`0001-<name>.json`) and `batch_report.json` are written. Both contain metadata only (never binary payloads).
- `--mode {safe,balanced,aggressive}`: Batch-wide processing mode (default: `safe`).
- `--dry-run`: Preview planned changes; zero output files written.
- `-r, --recursive`: Recursively scan directories for input files.
- `--json`: Emit strictly pure `BatchReport` JSON to `stdout`. Diagnostics and progress go to `stderr`. Cleaned file bytes are absent from `--json` output.

### Batch Exit Code Contract

| Exit Code | Semantic Contract |
| :--- | :--- |
| `0` | **All Successful**: Every item completed with `CLEANED`, `NO_CHANGE_REQUIRED`, or `INSPECTED`. |
| `1` | **Partial Success**: Batch infrastructure completed, but at least one item failed (`ERROR`, `UNSUPPORTED`, `VALIDATION_FAILED`). Successful outputs remain valid and accessible. |
| `2` | **Fatal Setup / Root Limit**: No valid inputs provided, invalid CLI arguments, or batch exceeded `WATERMARKS_MAX_BATCH_FILES` / `WATERMARKS_MAX_BATCH_TOTAL_BYTES` before processing. |

---

## 5. HTTP API: `POST /batch`

### Request Payload
```json
{
  "files": [
    { "name": "document.docx", "file": "<base64>" },
    { "name": "notes.txt", "file": "<base64>" }
  ],
  "mode": "safe",
  "dry_run": false
}
```

### Response Transport Envelope
The HTTP response strictly separates the canonical metadata report from the file payload delivery:
```json
{
  "ok": true,
  "report": {
    "schema_version": "2.1.0",
    "batch_id": "...",
    "operation": "clean",
    "mode": "safe",
    "dry_run": false,
    "started_at": "...",
    "finished_at": "...",
    "input_count": 2,
    "summary": {
      "total": 2,
      "cleaned": 1,
      "no_change": 1,
      "inspected": 0,
      "unsupported": 0,
      "validation_failed": 0,
      "errors": 0,
      "skipped": 0
    },
    "items": [
      {
        "index": 0,
        "input_path": "document.docx",
        "format": "docx",
        "status": "CLEANED",
        "report": { ... }
      },
      {
        "index": 1,
        "input_path": "notes.txt",
        "format": "txt",
        "status": "NO_CHANGE_REQUIRED",
        "report": { ... }
      }
    ],
    "privacy": { "network_used": false, "external_services": [] },
    "performance": { "elapsed_ms": 45.2 }
  },
  "outputs_included": true,
  "output_delivery": "inline",
  "outputs": [
    {
      "index": 0,
      "name": "document.docx",
      "sha256": "...",
      "content_base64": "<base64>"
    }
  ]
}
```

### Safety & Memory Bounds
1. **Distinct Limits**:
   - `WATERMARKS_MAX_BATCH_FILES`: Maximum item count allowed in a single batch (default: 100).
   - `WATERMARKS_MAX_BATCH_TOTAL_BYTES`: Maximum cumulative input size accepted (default: 200 MiB).
   - `WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES`: Maximum cumulative cleaned output bytes allowed to be serialized inline in an HTTP response (default: 32 MiB).
2. **Memory Amplification Protection**:
   - For 200 MiB of raw input, inlining up to 200 MiB would require: 200 MiB raw inputs + 200 MiB cleaned outputs + 267 MiB base64 strings + 267+ MiB serialized response JSON = **> 1.2 GiB resident RAM** (~6x amplification).
   - By capping inline delivery at `WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES` (32 MiB), the response base64 size is bounded to $\approx 42.7\text{ MiB}$ and response serialization to $\approx 45\text{ MiB}$.
3. **Check Before Base64 Encoding**:
   - Total raw output size is checked across cleaned items **before** calling `base64.b64encode`.
   - If total raw cleaned bytes exceed `WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES`:
     - Base64 encoding is **skipped entirely**; zero base64 memory amplification occurs.
     - `outputs_included = false`
     - `output_delivery = "not_available_inline"`
     - `outputs_omitted_reason` explains the limit threshold.
     - `outputs = []`
     - Canonical metadata report is returned completely intact.
4. **Dry-Run & Failure Output Elimination**:
   - When `dry_run: true`, `outputs_included = false`, `output_delivery = "dry_run"`, and `outputs = []`.
   - Items with status `ERROR`, `UNSUPPORTED`, `VALIDATION_FAILED`, or `NO_CHANGE_REQUIRED` yield **zero** entries in `outputs`.

---

## 6. Verification & Test Metrics

### Test Suite Execution
- `tests/test_batch_processor.py`: 16 tests covering fault isolation, deterministic ordering, collision safety, duplicate inputs, existing output protection, dry-run zero-write, state isolation, per-file reports, max files limit, max bytes limit, symlink protection, traversal containment, report privacy, canonical report payload exclusion, and reports-dir payload exclusion.
- `tests/test_batch_cli.py`: 7 tests covering JSON purity, human output formatting, partial success exit code 1, limit exceeded exit code 2, recursive directory processing, real console entrypoint execution (`uv run watermarks batch ...`), and CLI JSON payload exclusion.
- `tests/test_batch_api.py`: 9 tests covering real clean with explicit transport envelope, dry run zero payloads, fault isolation over HTTP, request validation (400), root batch limits (413), inline output limit enforcement (32 MiB threshold), limit checked before base64 encoding (zero memory amplification), zero network egress, and report privacy.

### Canonical Pytest Full Regression
```
1463 passed, 152 skipped, 0 failed, 0 warnings in 84.19s
```
- Net increase: +32 tests over pre-Phase 4 baseline (1431 -> 1463).
- Skipped: 152 (identical to Phase 3 baseline).
- Warnings: 0.
- Failures: 0.

### Lossless DOCX Frozen Core Verification
- `git diff v2.0.0 -- service/scripts/docx/`: **EMPTY** (0 lines changed).
- Golden DOCX SHA256: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (VERIFIED).
- Candidate DOCX SHA256: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (VERIFIED).
- Structural Fidelity Validator: **PASS** (204/204 paragraphs, 288/288 runs, 19/19 pages, identical visible text).
