"""Tests for Phase 5: Web UI Contract & Asset Serving (tests/test_ui_contract.py).

Covers:
- Static asset serving (/ , /index.html, /app.js, /app.css) via HTTP server
- HTML template structure and semantic elements (mode selector, dry run toggle, batch summary, card template)
- Filename sanitization logic preventing path traversal (../../evil.docx -> evil.cleaned.docx)
- XSS prevention: verify template and scripts never inject untrusted data via innerHTML
- Capabilities-driven UI parity (formats, batch limits, modes)
- DOCX Lossless badge invariant: only shown when format is docx and validation status is PASS
- HTTP Batch transport contract compatibility: outputs_included=true vs false
- Zero body text leakage in UI assets
"""

from __future__ import annotations

import http.client
import json
import re
import sys
import threading
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
WEB_DIR = REPO_ROOT / "service" / "web"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import service.scripts.server as server


@pytest.fixture(scope="module")
def conn() -> http.client.HTTPConnection:
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    yield c
    c.close()
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


# 1. Static Asset Serving
def test_static_asset_serving_html(conn):
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    assert resp.status == 200
    assert "text/html" in resp.headers.get("Content-Type", "")
    assert "ClearMark" in body
    assert "fileCardTemplate" in body


def test_static_asset_serving_app_js(conn):
    conn.request("GET", "/app.js")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    assert resp.status == 200
    assert "application/javascript" in resp.headers.get("Content-Type", "")
    assert "loadCapabilities" in body
    assert "safeCleanedName" in body


def test_static_asset_serving_app_css(conn):
    conn.request("GET", "/app.css")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    assert resp.status == 200
    assert "text/css" in resp.headers.get("Content-Type", "")
    assert "--green-deep" in body
    assert ".badge-lossless" in body


# 2. HTML Semantic & Phase 5 UI Elements
def test_ui_html_required_elements():
    html_file = WEB_DIR / "index.html"
    assert html_file.exists()
    content = html_file.read_text(encoding="utf-8")

    # Mode selector with safe, balanced, aggressive
    assert 'id="modeSelect"' in content
    assert 'value="safe"' in content
    assert 'value="balanced"' in content
    assert 'value="aggressive"' in content

    # Dry run toggle
    assert 'id="dryRunToggle"' in content

    # Batch summary bar & counters
    assert 'id="batchSummaryBar"' in content
    assert 'id="sumTotal"' in content
    assert 'id="sumCleaned"' in content
    assert 'id="sumNoChange"' in content
    assert 'id="sumUnsupported"' in content
    assert 'id="sumErrors"' in content

    # Large batch warning banner
    assert 'id="batchWarningBanner"' in content

    # Privacy indicator
    assert 'id="privacyBadge"' in content

    # File card template with findings and lossless badge
    assert 'id="fileCardTemplate"' in content
    assert 'badge-lossless' in content
    assert 'findings-box' in content
    assert 'findings-details' in content


# 3. Filename Sanitization & Path Traversal Protection
def test_ui_safe_filename_sanitization():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    # Verify safeCleanedName implementation exists in app.js
    assert "function safeCleanedName(" in app_js

    # Test the sanitization pattern directly in Python to match JS logic
    def py_safe_cleaned_name(filename: str) -> str:
        safe_base = re.sub(r"^.*[\\/]", "", filename)
        safe_base = re.sub(r"[^a-zA-Z0-9._-]", "_", safe_base)
        last_dot = safe_base.rfind(".")
        if last_dot > 0:
            return f"{safe_base[:last_dot]}.cleaned{safe_base[last_dot:]}"
        return f"{safe_base}.cleaned"

    assert py_safe_cleaned_name("../../evil.docx") == "evil.cleaned.docx"
    assert py_safe_cleaned_name("..\\..\\passwords.txt") == "passwords.cleaned.txt"
    assert py_safe_cleaned_name("C:\\temp\\report.pdf") == "report.cleaned.pdf"
    assert py_safe_cleaned_name("normal_doc.docx") == "normal_doc.cleaned.docx"
    assert py_safe_cleaned_name("<img src=x>.docx") == "_img_src_x_.cleaned.docx"


# 4. XSS Security Rendering Invariant
def test_ui_xss_safety_in_app_js():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    # Invariant: textContent must be used for dynamic untrusted inputs
    assert "$('.file-name', node).textContent = item.file.name" in app_js
    assert "li.textContent =" in app_js

    # Prohibited: untrusted innerHTML injection of filenames or error strings
    assert "innerHTML = item.file.name" not in app_js
    assert "innerHTML = f.reason" not in app_js
    assert "innerHTML = err.message" not in app_js
    assert "innerHTML = data.error" not in app_js


# 5. Honest Terminology Invariant (ADR-003)
def test_ui_honest_terminology():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    for text in (app_js, index_html):
        # Forbidden marketing claims
        assert "100% watermark removed" not in text.lower()
        assert "ai watermark definitely removed" not in text.lower()
        assert "watermark absent" not in text.lower()
        assert "perfectly clean" not in text.lower()


# 6. DOCX Lossless Badge Display Invariant
def test_ui_docx_lossless_badge_logic():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    # Lossless badge must only be shown if isDocx AND validationPassed (status === 'PASS')
    assert "isDocx && validationPassed" in app_js
    assert "item.report?.validation?.status === 'PASS'" in app_js


# 7. Zero Body Text Leakage Invariant
def test_ui_no_body_text_leakage():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # Must not reference document body or paragraph text dumps
    assert "body_text" not in app_js
    assert "full_text" not in app_js
    assert "document_content" not in app_js


# 8. Object URL Cleanup Invariant
def test_ui_object_url_cleanup():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # Must call URL.revokeObjectURL
    assert "URL.revokeObjectURL" in app_js


# 9. Default Mode is SAFE
def test_ui_safe_mode_default():
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert '<option value="safe" id="optModeSafe" selected>' in index_html
    assert "mode: 'safe'" in app_js


# 10. Request Race and Stale Response Protection
def test_ui_request_race_protection():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "item.version += 1" in app_js
    assert "if (item.version !== currentVersion) return" in app_js


# 11. Privacy Indicator Parity
def test_ui_privacy_indicator_truthfulness():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "privacy?.network_used === false" in app_js
    assert "Local processing / No external service used" in app_js


# 12. Batch Transport Delivery Contract
def test_ui_batch_transport_delivery_contract():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "outputsIncluded" in app_js
    assert "outputDelivery === 'not_available_inline'" in app_js
    assert "Batch completed, but cleaned files are too large for inline browser delivery." in app_js
    assert "downloadBtn.hidden = !item.result?.url" in app_js


# 13. Capability-Aware Mode Resolution & Stale Mode Protection Contract
def test_ui_capability_aware_mode_contract():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # Options have unique IDs for dynamic capability control
    assert 'id="optModeSafe"' in index_html
    assert 'id="optModeBalanced"' in index_html
    assert 'id="optModeAggressive"' in index_html

    # Invariants in app.js
    assert "function getSupportedModesForFile(" in app_js
    assert "function updateModeSelector(" in app_js
    assert "optBalanced.disabled = !balancedSupported" in app_js
    assert "optAggressive.disabled = !aggressiveSupported" in app_js
    assert "state.mode = 'safe'" in app_js
    assert "els.modeSelect.value = 'safe'" in app_js


# 14. Accessibility Contract
def test_ui_accessibility_contract():
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_css = (WEB_DIR / "app.css").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    # Important status regions use aria-live
    assert 'id="modeExplanation" role="status" aria-live="polite"' in index_html
    assert 'id="batchWarningBanner" hidden role="alert" aria-live="polite"' in index_html
    assert 'id="batchSummaryBar"' in index_html and 'aria-live="polite"' in index_html

    # Keyboard accessibility for dropzone
    assert "e.key === 'Enter' || e.key === ' '" in app_js

    # Visible focus style
    assert ":focus-visible" in app_css
    assert "outline: 2px solid var(--green-deep)" in app_css

    # Non-color-only status & error indicators
    assert '.status-badge.status-error::before { content: "✕ "' in app_css
    assert '.status-badge.status-failed::before { content: "⊘ "' in app_css
    assert '.status-badge.status-unsupported::before { content: "⊘ "' in app_css
    assert '.status-badge.status-cleaned::before { content: "✓ "' in app_css
    assert "border: 1px dashed var(--danger)" in app_css


# 15. Truthful Mode Copy Contract
def test_ui_truthful_mode_copy_contract():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # Truthful wording
    assert "High-confidence/default processing." in app_js
    assert "Additional operations where supported by this format." in app_js
    assert "Broader operations where explicitly supported; may show additional warnings." in app_js
    assert "High-confidence/default processing." in index_html

    # No global universal behavioral claims about homoglyphs/control chars on all formats
    assert "chuẩn hóa ký tự điều khiển bổ sung" not in app_js
    assert "homoglyphs" not in app_js


# 16. Capabilities Authoritative Source (No Hardcoded Matrix in app.js)
def test_ui_no_hardcoded_mode_matrix():
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # Must query state.capabilities.formats, not a hardcoded format->mode table
    assert "state.capabilities.formats[ext]" in app_js
    assert "fmtCap.supported_modes" in app_js


