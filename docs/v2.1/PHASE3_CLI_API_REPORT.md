# ClearMark v2.1 Phase 3 Report — Unified CLI & API Normalization

> **Phase**: Phase 3 (Unified CLI & API Normalization)  
> **Status**: PASS  
> **Baseline Commit**: `464270f`  
> **Frozen Core**: Lossless DOCX Subsystem (`service/scripts/docx/`)  
> **Golden DOCX SHA256**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d`  
> **Candidate DOCX SHA256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297`  

---

## 1. Executive Summary

Phase 3 establishes the canonical public interfaces for ClearMark v2.1:
1. **Canonical CLI (`watermarks`)**: Unified command grammar (`inspect`, `clean`, `verify`, `capabilities`) backed by `service/scripts/cli.py`.
2. **Deterministic Exit Codes**: Stable, machine-readable exit codes (0, 2, 3, 4, 5, 6, 10).
3. **HTTP REST Normalization**: `/inspect`, `/clean`, `/verify`, and `/capabilities` normalized to route through the universal `Pipeline` engine.
4. **Authoritative Capabilities**: `/capabilities` generates its format matrix directly from `service/scripts/format_policy.py`.
5. **Schema Parity & stdout Purity**: Strict parity between CLI `--json` output and HTTP API `CleaningReport` models. `stdout` emits valid JSON only, without banners or progress prose.
6. **Backward Compatibility**: Full compatibility maintained for legacy CLI wrappers (`clean_file.py`, `inspect_file.py`) and legacy HTTP clients.

---

## 2. Canonical CLI Grammar (`service/scripts/cli.py`)

### Command Structure
```bash
watermarks inspect <file> [--mode safe|balanced|aggressive] [--json]
watermarks clean <file> [--mode safe|balanced|aggressive] [--dry-run] [--in-place] [-o/--output <path>] [--json]
watermarks verify <original> <candidate> [--json]
watermarks capabilities [--json]
```

### Options Specification
- `--mode {safe, balanced, aggressive}`: Controls processing intensity and homoglyph aggression (default: `safe`).
- `--dry-run`: Previews planned mutations, computes invariants, and generates `CleaningReport` without modifying input or writing output files.
- `--in-place`: Atomically replaces the input file via a sibling temporary file only after invariant validation passes.
- `-o, --output <path>`: Explicit destination output path.
- `--json`: Strictly emits the canonical `CleaningReport` JSON to `stdout`. Diagnostics, deprecations, and logs go exclusively to `stderr`.

---

## 3. Exit Code Contract

| Code | Name | Semantic Contract |
| :--- | :--- | :--- |
| `0` | `SUCCESS` | Successful execution (inspected, cleaned, verified, or no change required). |
| `2` | `UNSUPPORTED` | Unsupported file format or unsupported capability requested for format. |
| `3` | `VALIDATION_FAILED` | Invariant validation failed; input file left untouched. |
| `4` | `INVALID_INPUT` | File not found, path is a directory, invalid CLI mode, conflicting options, or malformed container. |
| `5` | `DEPENDENCY_MISSING` | Required optional tool missing on system PATH. |
| `6` | `LIMIT_EXCEEDED` | File size or archive decompressed size exceeds safety thresholds. |
| `10` | `INTERNAL_ERROR` | Unhandled exception or unexpected system failure (no tracebacks in normal contract). |

---

## 4. HTTP API Normalization

### Endpoints Overview

| Endpoint | Method | Pipeline Routing | Response Model |
| :--- | :--- | :--- | :--- |
| `/inspect` | `POST` | `Pipeline.inspect()` | Canonical `CleaningReport` + legacy `suspicious` envelope |
| `/clean` | `POST` | `Pipeline.clean()` | Base64 `cleaned` payload + canonical `CleaningReport` (empty string on `dry_run: true`) |
| `/verify` | `POST` | `analyze_docx_fidelity(..., visual=False)` | Structural invariants status, hash comparison, invariant checks |
| `/capabilities` | `GET` | `FormatPolicyRegistry.get_default()` | Dynamic format policy matrix + legacy tool availability |

### HTTP Status Code Mapping

| Error Code | HTTP Status | Description |
| :--- | :--- | :--- |
| Success / Cleaned | `200 OK` | Operation succeeded. |
| `UNSUPPORTED_FORMAT` | `415 Unsupported Media Type` | File format is unrecognized or unsupported. |
| `INVALID_CONTAINER` | `400 Bad Request` | Malformed file container or invalid input parameters. |
| `VALIDATION_FAILED` | `422 Unprocessable Entity` | Post-cleaning invariant check failed or verify mismatch. |
| `OPTIONAL_DEPENDENCY_MISSING` | `424 Failed Dependency` | Tool required for requested operation is not present. |
| `PROCESSING_LIMIT_EXCEEDED` | `413 Payload Too Large` | Input exceeds maximum size cap (`MAX_INPUT_BYTES`). |
| `INTERNAL_ERROR` | `500 Internal Server Error` | Unexpected processing error. |

---

## 5. Backward Compatibility & Envelope Structure

### `/clean` Response Envelope
```json
{
  "ok": true,
  "kind": "container",
  "cleaned": "<base64>",
  "report": {
    "status": "CLEANED",
    "input": { "filename": "doc.docx", "format": "docx", "size": 1234, "sha256": "..." },
    "inspection": { ... },
    "policy": { ... },
    "mutation_plan": { ... },
    "validation": { "status": "PASS", "invariants": [...] },
    "output": { "changed": true, "would_change": true, "size": 1200, "sha256": "..." },
    "privacy": { "network_used": false },
    "performance": { "elapsed_ms": 42.1 },
    "stats": { "removed_count": 2 },
    "actions": ["docProps/core.xml: stripped Dublin Core creator"]
  }
}
```

### Legacy CLI Wrappers
`service/scripts/clean_file.py` and `service/scripts/inspect_file.py` remain fully functional:
- When invoked interactively, emit a deprecation warning to `stderr` pointing to `watermarks clean` / `watermarks inspect`.
- Never pollute `stdout` when `--json` is supplied.
- Respect `-q` / `--quiet` flags by omitting warnings entirely.

---

## 6. ADR-010 Policy Forwarder Audit
- In Phase 1, `service/scripts/pipeline_types.py` added a dynamic `__getattr__` forwarder for `FormatPolicy`, `FormatCapabilities`, and `FormatPolicyRegistry`.
- In Phase 3, all internal modules (`cli.py`, `server.py`, `pipeline.py`) import directly from `service/scripts/format_policy.py`.
- The `pipeline_types.__getattr__` forwarder emits an explicit `DeprecationWarning` when accessed to ensure external callers can safely migrate without sudden breaking changes.

---

## 7. Security, Invariant, and Privacy Verification
1. **Frozen DOCX Subsystem Invariant**:
   - `git diff v2.0.0 -- service/scripts/docx/` remains **100% EMPTY**.
   - Golden untouched hash: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d`
   - Candidate lossless hash: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297`
   - Master fidelity revalidation overall verdict: **PASS** (`verify_document_fidelity.py`).
2. **In-Place Atomic Safety**:
   - Validation failure leaves original file byte-identical and cleans up temporary sibling files.
3. **Zero Network Socket Activity**:
   - Verified via monkeypatched socket primitives during inspect and dry-run execution.
4. **Universal Report Privacy**:
   - Serialized reports contain no visible document text.

---

## 8. Contract Micro-Audit Verification

### Console Entry Point Registration
- **File**: `pyproject.toml`
- **Declaration**:
  ```toml
  [project.scripts]
  watermarks = "service.scripts.cli:main"
  ```
- **Invocation Distinctions**:
  - **Production/Installed**: `watermarks <command> [options]` (executable located at `.venv/Scripts/watermarks.exe` or system PATH).
  - **Development**: `uv run watermarks <command> [options]`.
- **Packaging Discovery**: Verified via `importlib.metadata.entry_points(group="console_scripts")` in `tests/test_console_entrypoint.py`.

### Real User Invocations & stdout Purity Tested
All five canonical commands were executed through the actual packaged entrypoint with `--json`:
1. `watermarks --help`: Exits 0, human-readable help text.
2. `watermarks inspect 01_GOLDEN_ORIGINAL_UNTOUCHED.docx --json`: Exits 0, single pure JSON object, zero prose.
3. `watermarks clean 01_GOLDEN_ORIGINAL_UNTOUCHED.docx --dry-run --json`: Exits 0, single pure JSON object, `changed=false`, `would_change=true`.
4. `watermarks verify 01_GOLDEN_ORIGINAL_UNTOUCHED.docx 04_CANDIDATE_LOSSLESS_OUTPUT.docx --json`: Exits 0, single pure JSON object, `status=PASS`.
5. `watermarks capabilities --json`: Exits 0, single pure JSON object with format policies and `verify_capabilities`.

### Verification Command Format Scope
- Verification is currently implemented and supported exclusively for DOCX structural fidelity checks.
- Non-DOCX inputs to `watermarks verify` return `ExitCode.UNSUPPORTED` (2) with `UNSUPPORTED_VERIFICATION_CAPABILITY`.
- Non-DOCX inputs to `POST /verify` return `HTTPStatus.UNSUPPORTED_MEDIA_TYPE` (415) with `UNSUPPORTED_VERIFICATION_CAPABILITY`.
- `FormatPolicyRegistry` truthfully exposes `verify_capabilities`: `("structural_invariants", "raw_opc_invariants", "visible_text_exact")` for DOCX, and empty tuples for other formats until dedicated adapters are built.

### ADR-005 Processing Mode Semantic Contract
- `SAFE`: Mandatory supported baseline, default for all formats, default for structured document formats.
- `BALANCED` / `AGGRESSIVE`: Permitted only where `FormatPolicy` explicitly enables them; must never bypass fidelity validation; produces explicit warnings rather than silently pretending stronger cleaning.

### Pytest Warnings Classification
- The 3 warnings on `pipeline_types.__getattr__` (`FormatPolicyRegistry`, `FormatPolicy`, `FormatCapabilities`) were evaluated:
  - **Class**: `DeprecationWarning`
  - **Source**: `service/scripts/pipeline_types.py`
  - **Test**: `tests/test_pipeline_data_model.py::test_format_policy_single_source_of_truth`
  - **Classification**: **EXPECTED** (validates ADR-010 deprecation forwarder for external callers).
  - **Resolution**: Wrapped in explicit `pytest.deprecated_call()` assertions within the test, eliminating unhandled pytest warnings.

