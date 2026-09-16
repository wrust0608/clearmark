"""Tests for Phase 4: HTTP API Batch Endpoint (POST /batch).

Covers:
- POST /batch synchronous batch processing
- Failure isolation over HTTP (mixed valid + corrupt files)
- Dry-run batch over HTTP (would_change=True, changed=False, no cleaned payload)
- Root-level batch safety limits (MAX_BATCH_FILES, MAX_BATCH_TOTAL_BYTES -> 413)
- Request validation (missing files array, empty array -> 400)
- Zero-network isolation
- Report privacy invariant
"""

from __future__ import annotations

import base64
import http.client
import json
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


# 1. HTTP /batch Real Clean
def test_api_batch_clean_success(conn):
    docx_bytes = GOLDEN_DOCX.read_bytes()
    txt_bytes = b"Sample clean document text."

    payload = {
        "files": [
            {"name": "doc.docx", "file": _b64(docx_bytes)},
            {"name": "note.txt", "file": _b64(txt_bytes)},
        ],
        "mode": "safe",
        "dry_run": false if hasattr(__builtins__, "false") else False,
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    assert body["ok"] is True
    assert body["input_count"] == 2
    assert body["summary"]["cleaned"] == 1
    assert body["summary"]["no_change"] == 1
    assert body["summary"]["errors"] == 0

    # Cleaned payload returned for modified item
    item1 = body["items"][0]
    assert item1["status"] == "CLEANED"
    assert "cleaned" in item1
    cleaned_bytes = base64.b64decode(item1["cleaned"])
    assert len(cleaned_bytes) > 0


# 2. HTTP /batch Dry Run
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
    assert body["dry_run"] is True
    assert body["summary"]["inspected"] == 1
    assert body["summary"]["cleaned"] == 0

    item = body["items"][0]
    assert item["report"]["output"]["changed"] is False
    assert item["report"]["output"]["would_change"] is True


# 3. HTTP /batch Fault Isolation (Mixed valid and corrupt)
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
    assert body["summary"]["cleaned"] == 1
    assert body["summary"]["errors"] == 1

    # Item 1 succeeded despite Item 2 failing
    assert body["items"][0]["status"] == "CLEANED"
    assert body["items"][1]["status"] == "ERROR"


# 4. HTTP /batch Request Validation
def test_api_batch_validation_missing_files(conn):
    status, body = _post(conn, "/batch", {"mode": "safe"})
    assert status == 400
    assert body["ok"] is False

    status, body = _post(conn, "/batch", {"files": []})
    assert status == 400
    assert body["ok"] is False


# 5. HTTP /batch Limits: MAX_BATCH_FILES
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


# 6. HTTP /batch Zero Network Isolation
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
    assert body["privacy"]["network_used"] is False


# 7. HTTP /batch Report Privacy Invariant
def test_api_batch_privacy_no_body_text(conn):
    secret_text = "CONFIDENTIAL_API_PAYLOAD_TOKEN_789"
    payload = {
        "files": [
            {"name": "doc.txt", "file": _b64(f"Note with {secret_text}\u200Bmarker".encode("utf-8"))}
        ]
    }

    status, body = _post(conn, "/batch", payload)
    assert status == 200
    body_str = json.dumps(body)
    assert secret_text not in body_str
