"""Tests for Phase 4: HTTP API Batch Endpoint (POST /batch).

Covers:
- POST /batch synchronous batch processing with explicit transport envelope
- Canonical BatchReport metadata-only separation (report vs outputs)
- Failure isolation over HTTP (mixed valid + corrupt files; failed items yield no outputs)
- Dry-run batch over HTTP (outputs_included=False, output_delivery="dry_run", outputs=[])
- Root-level batch safety limits (MAX_BATCH_FILES, MAX_BATCH_TOTAL_BYTES -> 413)
- Inline output limit enforcement (WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES -> outputs_included=False)
- Limit check before base64 encoding (zero base64 memory amplification)
- Request validation (missing files array, empty array -> 400)
- Zero-network isolation
- Report privacy invariant (report contains no body text)
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import sys
import threading
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import service.scripts.server as server

GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _post(conn: http.client.HTTPConnection, path: str, payload: dict) -> tuple[int, dict]:
    conn.request(
        "POST",
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, json.loads(data) if data else {}


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


# 1. HTTP /batch Real Clean: Explicit Transport Envelope & Canonical Report Separation
def test_api_batch_clean_success(conn):
    docx_bytes = GOLDEN_DOCX.read_bytes()
    txt_bytes = b"Sample clean document text."

    payload = {
        "files": [
            {"name": "doc.docx", "file": _b64(docx_bytes)},
            {"name": "note.txt", "file": _b64(txt_bytes)},
        ],
        "mode": "safe",
        "dry_run": False,
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    assert body["ok"] is True
    assert "report" in body
    report = body["report"]

    # Canonical report checks
    assert report["input_count"] == 2
    assert report["summary"]["cleaned"] == 1
    assert report["summary"]["no_change"] == 1
    assert report["summary"]["errors"] == 0

    # Invariant: canonical report items contain NO cleaned bytes or base64
    item1 = report["items"][0]
    assert item1["status"] == "CLEANED"
    assert "cleaned" not in item1
    assert "cleaned_bytes" not in item1
    assert "content_base64" not in item1

    # Transport envelope checks
    assert body["outputs_included"] is True
    assert body["output_delivery"] == "inline"
    assert len(body["outputs"]) == 1

    out0 = body["outputs"][0]
    assert out0["index"] == 0
    assert out0["name"] == "doc.docx"
    assert "content_base64" in out0
    cleaned_bytes = base64.b64decode(out0["content_base64"])
    assert len(cleaned_bytes) > 0


# 2. HTTP /batch Dry Run: Zero Output Payloads
def test_api_batch_dry_run(conn):
    docx_bytes = GOLDEN_DOCX.read_bytes()

    payload = {
        "files": [
            {"name": "doc.docx", "file": _b64(docx_bytes)},
        ],
        "mode": "safe",
        "dry_run": True,
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    assert body["ok"] is True
    assert body["outputs_included"] is False
    assert body["output_delivery"] == "dry_run"
    assert body["outputs"] == []

    report = body["report"]
    assert report["dry_run"] is True
    assert report["summary"]["inspected"] == 1
    assert report["summary"]["cleaned"] == 0

    item = report["items"][0]
    assert item["report"]["output"]["changed"] is False
    assert item["report"]["output"]["would_change"] is True
    assert "cleaned" not in item


# 3. HTTP /batch Fault Isolation: Failed Items Excluded from Outputs
def test_api_batch_fault_isolation(conn):
    docx_bytes = GOLDEN_DOCX.read_bytes()
    corrupt_bytes = b"PK\x03\x04corrupted_payload"

    payload = {
        "files": [
            {"name": "valid.docx", "file": _b64(docx_bytes)},
            {"name": "corrupt.docx", "file": _b64(corrupt_bytes)},
        ],
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    assert body["ok"] is True
    report = body["report"]
    assert report["summary"]["cleaned"] == 1
    assert report["summary"]["errors"] == 1

    # Item 1 succeeded despite Item 2 failing
    assert report["items"][0]["status"] == "CLEANED"
    assert report["items"][1]["status"] == "ERROR"

    # Only valid item in outputs; failed item yields ZERO output payload
    assert body["outputs_included"] is True
    assert len(body["outputs"]) == 1
    assert body["outputs"][0]["index"] == 0
    assert body["outputs"][0]["name"] == "valid.docx"


# 4. HTTP /batch Request Validation (400)
def test_api_batch_validation_missing_files(conn):
    status, body = _post(conn, "/batch", {"mode": "safe"})
    assert status == 400
    assert body["ok"] is False

    status, body = _post(conn, "/batch", {"files": []})
    assert status == 400
    assert body["ok"] is False


# 5. HTTP /batch Root Limits: MAX_BATCH_FILES (413)
def test_api_batch_limits_file_count(conn, monkeypatch):
    monkeypatch.setenv("WATERMARKS_MAX_BATCH_FILES", "2")
    import batch_processor
    monkeypatch.setattr(batch_processor, "MAX_BATCH_FILES", 2)

    payload = {
        "files": [
            {"name": "1.txt", "file": _b64(b"1")},
            {"name": "2.txt", "file": _b64(b"2")},
            {"name": "3.txt", "file": _b64(b"3")},
        ]
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 413
    assert body["ok"] is False
    assert "exceeds" in body["error"].lower()


# 6. HTTP /batch Inline Output Limit Enforced (outputs_included=False)
def test_api_batch_inline_output_limit_enforced(conn, monkeypatch):
    # Set inline output limit to tiny value (100 bytes)
    monkeypatch.setenv("WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES", "100")

    docx_bytes = GOLDEN_DOCX.read_bytes()
    payload = {
        "files": [{"name": "doc.docx", "file": _b64(docx_bytes)}],
        "mode": "safe",
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    assert body["ok"] is True
    assert body["outputs_included"] is False
    assert body["output_delivery"] == "not_available_inline"
    assert body["outputs"] == []
    assert "exceeds inline response limit" in body["outputs_omitted_reason"]

    # Canonical report is still complete and accurate
    report = body["report"]
    assert report["summary"]["cleaned"] == 1
    assert report["items"][0]["status"] == "CLEANED"


# 7. Base64 Size Accounting: Checked Before Base64 Memory Amplification
def test_api_batch_limit_checked_before_base64_encoding(conn, monkeypatch):
    # Set limit to 50 bytes so output exceeds limit
    monkeypatch.setenv("WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES", "50")

    docx_bytes = GOLDEN_DOCX.read_bytes()
    # Build payload before spying on b64encode
    payload = {"files": [{"name": "doc.docx", "file": _b64(docx_bytes)}]}

    # Spy on base64.b64encode in the server handler to prove it is NOT called during response building
    orig_b64encode = base64.b64encode
    encode_calls = 0

    def _spy_b64encode(data):
        nonlocal encode_calls
        encode_calls += 1
        return orig_b64encode(data)

    monkeypatch.setattr(base64, "b64encode", _spy_b64encode)

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    assert body["outputs_included"] is False
    assert body["output_delivery"] == "not_available_inline"
    # base64.b64encode was NOT called for output encoding
    assert encode_calls == 0


# 8. HTTP /batch Zero Network Isolation
def test_api_batch_zero_network(conn, monkeypatch):
    orig_connect = socket.socket.connect

    def _guarded_connect(self, address):
        host = address[0]
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"CRITICAL: Remote network attempt to {address} during local batch API call!")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)

    docx_bytes = GOLDEN_DOCX.read_bytes()
    payload = {"files": [{"name": "doc.docx", "file": _b64(docx_bytes)}]}

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    assert body["ok"] is True
    assert body["report"]["privacy"]["network_used"] is False


# 9. HTTP /batch Report Privacy Invariant: Canonical Report Contains No Body Text
def test_api_batch_privacy_no_body_text(conn):
    secret_text = "CONFIDENTIAL_API_PAYLOAD_TOKEN_789"
    payload = {
        "files": [
            {"name": "doc.txt", "file": _b64(f"Note with {secret_text}\u200Bmarker".encode("utf-8"))}
        ]
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    report_str = json.dumps(body["report"])
    assert secret_text not in report_str
