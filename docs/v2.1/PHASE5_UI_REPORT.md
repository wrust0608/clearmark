# Phase 5: ClearMark v2.1 Web UI Enhancements Report

**Date**: 2026-09-16  
**Status**: PASS / COMPLETED  
**Baseline Commit**: `cd263066d5968370014f87cdd4b2e572239b40ef` (Phase 4)  
**Full Pytest Regression**: 1477 passed, 152 skipped, 0 failed, 0 warnings in 82.36s  
**Node.js Unit Tests**: 6 passed, 0 failed  
**Browser Gate**: Google Chrome 153.0.8010.48 — 15/15 scenario steps passed  
**DOCX Frozen Core**: 100% untouched (`git diff v2.0.0 -- service/scripts/docx/` is EMPTY)  

---

## 1. Executive Summary

Phase 5 delivers a polished, capabilities-first, inspection-first, failure-isolated multi-file & batch web user interface over the canonical ClearMark v2.1 API. It upholds all core invariants:
1. **Capabilities-First**: Bootstraps dynamically from `GET /capabilities`. Does not hard-code file formats, modes, or backend tooling limits.
2. **Inspection-First**: Files added to the queue undergo non-destructive inspection (`POST /inspect`) before cleaning.
3. **Multi-File Queue & Card State Determinism**: Independent card lifecycle with states: `QUEUED`, `INSPECTING`, `READY`, `CLEANING`, `CLEANED`, `NO CHANGE`, `PREVIEW READY`, `UNSUPPORTED`, `VALIDATION FAILED`, `ERROR`.
4. **Honest Terminology (ADR-003)**: Eliminates all misleading marketing claims ("100% watermark removed", "AI absent", "perfectly clean"). Uses truthful labels ("Supported markers cleaned", "No supported marker detected").
5. **DOCX Lossless Badge**: Displayed (`LOSSLESS VALIDATION PASSED`) strictly when backend runtime report confirms validation status `PASS` on a DOCX document. Never derived from filename alone.
6. **HTTP Batch Transport Delivery**: Full adherence to the Phase 4 batch contract (`outputs_included=true` delivers inline downloads; `outputs_included=false` / `not_available_inline` provides informative explanations and prevents broken download links).
7. **Security & Memory Safety**: Untrusted inputs (filenames, error strings, finding details) render via safe DOM APIs (`textContent`). Download filenames are sanitized against path traversal (`../../evil.docx` -> `evil.cleaned.docx`). All Object URLs (`URL.createObjectURL`) are reliably revoked (`URL.revokeObjectURL`) upon card removal, queue clear, or reprocessing.
8. **Request Race Safety**: Per-card version counters discard stale HTTP responses.

---

## 2. Architecture & File Inventory

### Frontend Architecture Classification
- **Framework**: Pure Vanilla HTML5 / CSS3 / ES6+ JavaScript. No React, Vue, Svelte, or runtime bundling needed.
- **Design System**: Strict CSS variable token system (`--ink`, `--paper`, `--surface`, `--border`, `--green`, `--green-deep`, `--shadow`, `--radius`, `--space-*`). High information density, calm technical forensic styling, dark/light theme awareness, fully responsive layout.
- **Asset Serving**: Built-in HTTP server (`service/scripts/server.py`) routes `/`, `/index.html`, `/app.js`, `/app.css` directly without external web servers.

### Files Modified & Created
| File | Action | Role |
|---|---|---|
| `service/scripts/server.py` | MODIFIED | Static asset handlers for `/`, `/index.html`, `/app.js`, `/app.css` |
| `service/web/index.html` | MODIFIED | Mode selector, dry-run toggle, summary counters, large-batch warning, card template |
| `service/web/app.css` | MODIFIED | Forensic design tokens, status badge styles, findings drawer, responsive layout |
| `service/web/app.js` | MODIFIED | Capabilities bootstrap, queue manager, inspect/clean/batch controller, safe DOM renderer |
| `tests/test_ui_contract.py` | NEW | 14 pytest integration tests verifying static serving, XSS safety, and contract invariants |
| `tests/test_web_app.mjs` | NEW | 6 Node.js unit tests for pure frontend functions (formatting, sanitization, envelope decoding) |
| `tests/smoke_browser.mjs` | NEW | Native CDP automation executing the full 15-step real browser smoke gate scenario |
| `tests/fixtures/unsupported_file.xyz` | NEW | Unsupported file fixture for testing batch partial failure isolation in UI |

---

## 3. Capabilities-First & Mode Selector Contract

- On load, `loadCapabilities()` fetches `GET /capabilities`. Supported formats, optional tools, and backend limits are rendered dynamically. If unreachable, a visible offline state is displayed.
- **Mode Selector**:
  - `SAFE` (Default): Preserves structure and formatting using high-confidence cleaning operations.
  - `BALANCED`: Expands metadata inspection and standardizes control characters.
  - `AGGRESSIVE`: Experimental normalization of homoglyphs.
- **Dry-Run Toggle**: Switches operation to simulation mode (`dry_run=true`), rendering `PREVIEW READY` with truthful `would_change` feedback and suppressing download buttons.

---

## 4. Real Browser Smoke Gate Verification (Section 45)

Automated via Chrome DevTools Protocol (`tests/smoke_browser.mjs`) on real installed Google Chrome (`C:\Program Files\Google\Chrome\Application\chrome.exe`):

- **Browser**: Google Chrome `153.0.8010.48`
- **Results**: 15/15 steps PASSED:
  1. Open UI: Title, server state (`Sẵn sàng · vdev`), and capabilities (`23 formats`) rendered cleanly.
  2. Select Golden DOCX (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`): Card created with unique ID.
  3. Auto-Inspection: Transitions `QUEUED` -> `INSPECTING` -> `READY`. Findings displayed: `"Phát hiện: 2 bề mặt metadata / dấu vết"`.
  4. Mode Selection: `SAFE` selected by default.
  5. Dry-Run Execution: Clicked dry-run preview.
  6. Would-Change Feedback: Displays `PREVIEW READY` with detail: `"Xem trước: Sẽ làm sạch các dấu vết phát hiện (Dry Run: Tệp không bị sửa)"`.
  7. No Download in Dry-Run: Verified download button is strictly hidden.
  8. Actual Clean Execution: Dry-run unchecked; clean button clicked.
  9. Validation Passes: Transitions to `CLEANED`. DOCX Lossless badge (`LOSSLESS VALIDATION PASSED`) becomes visible.
  10. Download Available: Download button appears with sanitized filename.
  11. Multi-File Addition: Added `sample_watermarked.txt` and `unsupported_file.xyz`.
  12. Batch Execution: Clicked `Làm sạch tất cả` (`POST /batch`).
  13. Individual Card States:
      - `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`: `CLEANED`, download visible.
      - `sample_watermarked.txt`: `CLEANED`, download visible.
      - `unsupported_file.xyz`: `UNSUPPORTED`, download hidden.
  14. Partial Failure Isolation: Summary reflects `Total: 3, Cleaned: 2, Unsupported: 1`. Failure on item 2 does not erase or corrupt items 0 and 1.
  15. Page Reload: Page reloads cleanly with empty queue and online server status.

---

## 5. Frozen Core & Golden Invariant Verification

1. **DOCX Frozen Core Diff**:
   ```bash
   git diff v2.0.0 -- service/scripts/docx/
   # Output: EMPTY (0 lines changed)
   ```
2. **Golden DOCX SHA256**:
   `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (VERIFIED UNCHANGED)
3. **Candidate DOCX SHA256**:
   `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (VERIFIED UNCHANGED)

---

## 6. Regression Test Summary

- **Full Pytest Regression**:
  ```
  1477 passed, 152 skipped, 0 failed, 0 warnings in 82.36s
  ```
- **Node.js Frontend Unit Tests**:
  ```
  6 passed, 0 failed in 88ms
  ```
- **Browser Gate**:
  ```
  15/15 scenario checks passed in Google Chrome 153.0.8010.48
  ```
