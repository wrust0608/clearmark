# Phase 5: ClearMark v2.1 Web UI Enhancements & Micro-Audit Report

**Date**: 2026-09-16  
**Status**: PASS / COMPLETED  
**Baseline Commit**: `cd263066d5968370014f87cdd4b2e572239b40ef` (Phase 4)  
**Full Pytest Regression**: 1481 passed, 152 skipped, 0 failed, 0 warnings in 89.49s  
**Node.js Unit Tests**: 9 passed, 0 failed  
**UI Contract Pytest**: 18 passed, 0 failed  
**Real Browser Smoke Gate**: Google Chrome 153.0.8010.48 — 19/19 scenario steps passed  
**DOCX Frozen Core**: 100% untouched (`git diff v2.0.0 -- service/scripts/docx/` is EMPTY)  
**Golden DOCX Hash**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` (VERIFIED UNCHANGED)  
**Candidate DOCX Hash**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` (VERIFIED UNCHANGED)  

---

## 1. Executive Summary

Phase 5 delivers a capabilities-driven, inspection-first, failure-isolated multi-file and batch web interface over the canonical ClearMark v2.1 API. Following the Phase 5 Micro-Audit, all contracts and invariants have been verified and enforced:

1. **Processing Mode Source of Truth**:
   - Single authoritative pipeline: `FormatPolicyRegistry -> GET /capabilities -> UI`.
   - Zero hardcoded format->mode tables in `service/web/app.js`.
   - `FormatPolicy` in `service/scripts/format_policy.py` declares supported modes per format (`supported_modes`).
   - SVG is registered with `supported_modes=("safe",)`.
   - The UI inspects `state.capabilities.formats[ext]?.supported_modes` dynamically.
2. **SAFE-Only Format & Dynamic Mode Disabling**:
   - When a format supporting SAFE only (such as SVG) is added to the UI, the UI immediately disables `BALANCED` (`#optModeBalanced.disabled = true`) and `AGGRESSIVE` (`#optModeAggressive.disabled = true`).
   - The UI never allows the user to believe stronger processing will occur when backend policy forbids it.
3. **Invalid / Stale Mode Protection**:
   - When a user selects `BALANCED` or `AGGRESSIVE` for a format supporting stronger modes (e.g. DOCX), and then adds or switches to a SAFE-only format (e.g. SVG), the UI resets the selection immediately to SAFE (`state.mode = 'safe'`, `#modeSelect.value = 'safe'`), displays an alert toast, and updates the mode explanation.
4. **Truthful Mode Descriptions**:
   - Global behavioral claims about homoglyphs and control characters have been removed from frontend copy because they are format-specific (e.g. not applicable to images or vector files).
   - Standardized truthful copy:
     - `SAFE`: "High-confidence/default processing."
     - `BALANCED`: "Additional operations where supported by this format."
     - `AGGRESSIVE`: "Broader operations where explicitly supported; may show additional warnings."
5. **Concrete Accessibility Evidence**:
   - Keyboard accessible: File picker operable via keyboard (`#browseButton` click, Space/Enter on `#dropZone`).
   - Mode selector keyboard accessible: Standard `<select>` element operable via Tab and Arrow keys.
   - Buttons have accessible names: Explicit text or `aria-label` on all buttons.
   - Dynamic status regions use `role="status"` or `role="alert"` with `aria-live="polite"`.
   - Visible focus styling enforced via `:focus-visible` with `outline: 2px solid var(--green-deep); outline-offset: 2px;`.
   - Statuses and errors are not communicated by color alone: distinct text badges (`ERROR`, `VALIDATION FAILED`, `UNSUPPORTED`, `CLEANED`), symbol prefixes (`✕ `, `⊘ `, `✓ `), and dashed border styling on error cards.
6. **`outputs_included=false` / `not_available_inline` Browser UX**:
   - In accordance with the Phase 4 batch contract, oversized batches returning `outputs_included=false` and `output_delivery="not_available_inline"` preserve successful item status (`CLEANED`), suppress broken download buttons, and explicitly display `"Batch completed, but cleaned files are too large for inline browser delivery."` without falsely claiming batch failure.
7. **XSS & Path Traversal Security**:
   - Malicious filenames (`<img src=x onerror=alert(1)>.docx`) render strictly via `textContent`, producing 0 DOM element injections and 0 script executions.
   - Filenames are sanitized for safe downloads (`_img_src_x_onerror_alert_1__.cleaned.docx`).
   - Object URLs are strictly revoked upon card removal or replacement.

---

## 2. Capabilities Invariant Claims Verification

| Metric / Claim | Result | Evidence |
|---|---|---|
| Hard-coded supported format matrix | **NO** | Rendered purely from `GET /capabilities` (`state.capabilities.formats`) |
| Hard-coded format->mode matrix | **NO** | Resolved dynamically via `getSupportedModesForFile(item)` from `state.capabilities.formats[ext].supported_modes` |
| Hard-coded backend byte limits | **NO** | Dynamically read from `state.capabilities?.batch_limits?.max_batch_inline_output_bytes` |
| DOCX Lossless Core Diff | **EMPTY** | `git diff v2.0.0 -- service/scripts/docx/` produces 0 lines |
| Golden DOCX Hash Preserved | **MATCH** | `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` |
| Candidate DOCX Hash Preserved | **MATCH** | `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297` |

---

## 3. Real Browser Smoke Gate Verification (Google Chrome 153.0.8010.48)

Automated via Chrome DevTools Protocol (`tests/smoke_browser.mjs`):

- **Browser**: Google Chrome `153.0.8010.48`
- **Result**: **19/19 scenario steps PASSED**:
  1. Open UI: Title, server state (`Sẵn sàng · vdev`), and formats (23 formats) rendered cleanly.
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
  16. **SAFE-Only Format & Stale Mode Protection**:
      - Added Golden DOCX, switched to `BALANCED`.
      - Added `sample_meta.svg` (SAFE-only policy).
      - Verified `#optModeBalanced.disabled === true` and `#optModeAggressive.disabled === true`.
      - Verified mode reset to `safe` (`#modeSelect.value === 'safe'`).
  17. **Accessibility Verification**:
      - Verified `dropZone` has `role="button"`, `tabindex="0"`.
      - Verified `fileInput` has `aria-label="Chọn tệp tải lên"`.
      - Verified `modeExplanation` has `role="status"` and `aria-live="polite"`.
      - Verified `:focus-visible` rule exists in active CSS stylesheets.
  18. **`outputs_included=false` / `not_available_inline` Browser UX**:
      - Dispatched batch response with `outputs_included: false, output_delivery: "not_available_inline"`.
      - Card marked `CLEANED`.
      - Download button strictly hidden (`hidden === true`).
      - Card detail explicitly states: `"Batch completed, but cleaned files are too large for inline browser delivery."`.
      - Card does not have `error` CSS class.
  19. **XSS / Malicious Filename textContent Safety**:
      - Added file named `<img src=x onerror=alert(1)>.docx`.
      - Rendered file name in DOM: `"<img src=x onerror=alert(1)>.docx"`.
      - Injected `<img>` tags found in DOM: `0`.
      - XSS alert fired: `false`.

---

## 4. Test Verification Suite

### Node.js Frontend Unit Tests (`tests/test_web_app.mjs`)
- 9 tests, 0 failures:
  - `formatBytes` units formatting
  - `safeCleanedName` path traversal protection
  - Card state mapping and status labels completeness
  - DOCX Lossless badge predicate strictness
  - Batch summary mathematical reconciliation
  - HTTP Batch response transport envelope decoding
  - Capability-driven mode resolution and stale mode protection
  - HTTP Batch `outputs_included=false` / `not_available_inline` UX handling
  - XSS malicious filename safe handling

### Pytest UI Contract Tests (`tests/test_ui_contract.py`)
- 18 tests, 0 failures:
  - Static asset serving (`/`, `/index.html`, `/app.js`, `/app.css`)
  - HTML semantic elements & option IDs (`optModeSafe`, `optModeBalanced`, `optModeAggressive`)
  - Safe filename sanitization regex parity
  - XSS security rendering invariants (zero `innerHTML` for dynamic text)
  - Honest terminology invariant (ADR-003)
  - DOCX Lossless badge display predicate
  - Zero body text leakage in UI assets
  - Object URL cleanup (`URL.revokeObjectURL`)
  - Default mode SAFE invariant
  - Request race & stale response protection (`item.version`)
  - Privacy indicator truthfulness (`privacy.network_used`)
  - Batch transport delivery contract
  - Capability-aware mode resolution & stale mode protection contract
  - Accessibility contract (`aria-live`, `:focus-visible`, glyph indicators, dashed error borders)
  - Truthful mode copy contract (zero universal homoglyph/control character claims)
  - Capabilities authoritative source contract (zero hardcoded format->mode tables in `app.js`)
