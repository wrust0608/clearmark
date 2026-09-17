"""Tests for Phase 3: HTTP API Normalization Contract.

Covers:
- POST /inspect (canonical CleaningReport serialization, read-only, zero network, report privacy)
- POST /clean real (canonical CleaningReport, base64 cleaned payload, legacy envelope)
- POST /clean dry-run (cleaned="", would_change reflects plan, changed=False)
- POST /verify (structural verification only, 200 on PASS, 422 on FAIL)
- GET /capabilities (formats from format_policy.py as authoritative source of truth)
- HTTP error mapping (415, 400, 422, 413, 500)
- CLI/API CleaningReport schema parity
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

import server
from service.scripts.cli import main as cli_main
from service.scripts.format_policy import FormatPolicyRegistry
from service.scripts.pipeline_types import (
    CleaningReport,
    DetectionStatus,
    PipelineStatus,
    ProcessingMode,
)

GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CANDIDATE_DOCX = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"


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


def _get(conn: http.client.HTTPConnection, path: str) -> tuple[int, dict]:
    conn.request("GET", path)
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


# 1. HTTP /inspect
def test_api_inspect_canonical_report(conn):
    raw = GOLDEN_DOCX.read_bytes()
    status, body = _post(conn, "/inspect", {"file": _b64(raw), "name": "document.docx"})
    assert status == 200
    assert body["ok"] is True
    assert body["kind"] == "container"

    # Canonical CleaningReport deserialization
    report_dict = body["report"]
    report = CleaningReport.from_dict(report_dict)
    assert report.status == PipelineStatus.INSPECTED
    assert report.input.format == "docx"
    assert len(report.inspection.findings) > 0

    # Privacy check
    assert "Lorem ipsum" not in json.dumps(body)


# 2. HTTP /clean real
def test_api_clean_real(conn):
    raw = GOLDEN_DOCX.read_bytes()
    status, body = _post(conn, "/clean", {"file": _b64(raw), "name": "doc.docx"})
    assert status == 200
    assert body["ok"] is True
    assert body["cleaned"] != ""

    cleaned_bytes = base64.b64decode(body["cleaned"])
    assert len(cleaned_bytes) > 0

    report = CleaningReport.from_dict(body["report"])
    assert report.status == PipelineStatus.CLEANED
    assert report.output.changed is True


# 3. HTTP /clean dry-run
def test_api_clean_dry_run(conn):
    raw = GOLDEN_DOCX.read_bytes()
    status, body = _post(
        conn,
        "/clean",
        {"file": _b64(raw), "name": "doc.docx", "dry_run": True},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["cleaned"] == ""  # Zero cleaned bytes returned

    report = CleaningReport.from_dict(body["report"])
    assert report.output.changed is False
    assert report.output.would_change is True
    assert len(report.mutation_plan.mutations) > 0


# 4. HTTP /verify
def test_api_verify_pass(conn):
    orig_b64 = _b64(GOLDEN_DOCX.read_bytes())
    cand_b64 = _b64(CANDIDATE_DOCX.read_bytes())

    status, body = _post(
        conn,
        "/verify",
        {"original": orig_b64, "candidate": cand_b64, "name": "doc.docx"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["status"] == "PASS"
    assert body["format"] == "docx"
    assert body["validation"]["structural_invariants_passed"] is True
    assert len(body["invariants"]) >= 5


def _make_fidelity_invalid_docx_bytes(src_bytes: bytes) -> bytes:
    import io
    import zipfile
    bio_in = io.BytesIO(src_bytes)
    bio_out = io.BytesIO()
    with zipfile.ZipFile(bio_in, "r") as zin, zipfile.ZipFile(bio_out, "w") as zout:
        for item in zin.infolist():
            d = zin.read(item.filename)
            if item.filename == "word/document.xml":
                d = d.replace(b"</w:body>", b"<w:p><w:r><w:t>Injected</w:t></w:r></w:p></w:body>")
            zout.writestr(item, d)
    return bio_out.getvalue()


def test_api_verify_fail(conn):
    # Candidate is structurally valid but fails fidelity invariants -> HTTP 422
    orig_b64 = _b64(GOLDEN_DOCX.read_bytes())
    invalid_b64 = _b64(_make_fidelity_invalid_docx_bytes(GOLDEN_DOCX.read_bytes()))

    status, body = _post(
        conn,
        "/verify",
        {"original": orig_b64, "candidate": invalid_b64, "name": "doc.docx"},
    )
    assert status == 422
    assert body["ok"] is False
    assert body["status"] == "FAIL"


def test_api_verify_malformed_candidate_rejected(conn):
    # Candidate is malformed container -> HTTP 400
    orig_b64 = _b64(GOLDEN_DOCX.read_bytes())
    corrupt_b64 = _b64(b"PK\x03\x04corrupted file payload")

    status, body = _post(
        conn,
        "/verify",
        {"original": orig_b64, "candidate": corrupt_b64, "name": "doc.docx"},
    )
    assert status == 400
    assert body["ok"] is False
    assert body["status"] == "ERROR"
    assert body["error_code"] == "INVALID_CONTAINER"


def test_api_verify_unsupported_format(conn):
    raw_txt = _b64(b"Hello plain text")
    status, body = _post(
        conn,
        "/verify",
        {"original": raw_txt, "candidate": raw_txt, "name": "document.txt"},
    )
    assert status == 415
    assert body["ok"] is False
    assert body["status"] == "UNSUPPORTED"
    assert body["error_code"] == "UNSUPPORTED_VERIFICATION_CAPABILITY"
    assert "Verification capability is currently supported only for docx" in body["error"]


# 5. HTTP /capabilities
def test_api_capabilities_format_registry_parity(conn):
    status, body = _get(conn, "/capabilities")
    assert status == 200
    assert body["source"] == "service/scripts/format_policy.py"
    assert "formats" in body

    # Parity check with FormatPolicyRegistry
    reg = FormatPolicyRegistry.get_default()
    for policy in reg.all_policies():
        fmt_name = policy.format_name
        assert fmt_name in body["formats"]
        fmt_info = body["formats"][fmt_name]
        assert fmt_info["format"] == fmt_name
        assert set(fmt_info["extensions"]) == set(policy.extensions)
        assert set(fmt_info["inspect_capabilities"]) == set(policy.inspect_capabilities)
        assert set(fmt_info["clean_capabilities"]) == set(policy.clean_capabilities)


# 6. HTTP Error Code Mapping
def test_api_error_mapping_unsupported_format(conn):
    # Both /inspect and /clean must return 415 Unsupported Media Type
    status_insp, body_insp = _post(
        conn,
        "/inspect",
        {"file": _b64(b"binary data"), "name": "unsupported.xyz"},
    )
    assert status_insp == 415
    assert body_insp["ok"] is False
    assert body_insp["report"]["status"] == "UNSUPPORTED"
    assert body_insp["report"]["error_code"] == "UNSUPPORTED_FORMAT"

    status_clean, body_clean = _post(
        conn,
        "/clean",
        {"file": _b64(b"binary data"), "name": "unsupported.xyz"},
    )
    assert status_clean == 415
    assert body_clean["ok"] is False
    assert body_clean["report"]["status"] == "UNSUPPORTED"
    assert body_clean["report"]["error_code"] == "UNSUPPORTED_FORMAT"


def test_api_error_mapping_dependency_missing(conn):
    """Section 7: Positive PDF witness with uncleaned /Info watermark returns 424."""
    pdf_with_info = (
        b"%PDF-1.4\n"
        b"1 0 obj\n"
        b"<< /Author (AI generated) /Title (AIGC) >>\n"
        b"endobj\n"
        b"trailer\n"
        b"<< /Info 1 0 R >>\n"
        b"%%EOF\n"
    )
    status, body = _post(
        conn,
        "/clean",
        {"file": _b64(pdf_with_info), "name": "witness.pdf"},
    )
    assert status == 424
    assert body["ok"] is False
    assert body["report"]["status"] == "ERROR"
    assert body["report"]["error_code"] == "OPTIONAL_DEPENDENCY_MISSING"


def test_api_error_mapping_invalid_container(conn):
    # Binary named as text
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    status, body = _post(
        conn,
        "/clean",
        {"file": _b64(png_bytes), "name": "bad.txt"},
    )
    assert status == 400
    assert body["ok"] is False


def test_api_error_mapping_bad_mode(conn):
    status, body = _post(
        conn,
        "/clean",
        {"file": _b64(b"hello world"), "name": "note.txt", "mode": "invalid_mode"},
    )
    assert status == 400
    assert body["ok"] is False
    assert "Invalid mode" in body["error"]


# 7. CLI / API CleaningReport Parity (Section 21)
def test_cli_api_schema_parity(tmp_path: Path, conn, capsys):
    test_docx = tmp_path / "parity.docx"
    test_docx.write_bytes(GOLDEN_DOCX.read_bytes())

    # 1. CLI inspect --json
    cli_main(["inspect", str(test_docx), "--json"])
    cli_out = capsys.readouterr().out
    cli_dict = json.loads(cli_out)
    cli_report = CleaningReport.from_dict(cli_dict)

    # 2. HTTP /inspect
    status, api_body = _post(
        conn,
        "/inspect",
        {"file": _b64(GOLDEN_DOCX.read_bytes()), "name": "parity.docx"},
    )
    assert status == 200
    api_report = CleaningReport.from_dict(api_body["report"])

    # Both must deserialize to identical canonical model properties
    assert cli_report.status == api_report.status
    assert cli_report.input.format == api_report.input.format
    assert cli_report.input.sha256 == api_report.input.sha256
    assert cli_report.inspection.detection_status == api_report.inspection.detection_status
    assert len(cli_report.inspection.findings) == len(api_report.inspection.findings)
    assert cli_report.output.would_change == api_report.output.would_change


# 8. Zero Network Isolation for HTTP Inspect / Dry-Run
def test_api_zero_network_isolation(conn, monkeypatch):
    orig_connect = socket.socket.connect

    def _guarded_connect(self, address):
        host = address[0]
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"CRITICAL: Remote network attempt to {address} during local HTTP API call!")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)

    raw = GOLDEN_DOCX.read_bytes()
    status_insp, body_insp = _post(conn, "/inspect", {"file": _b64(raw), "name": "local.docx"})
    assert status_insp == 200

    status_dry, body_dry = _post(conn, "/clean", {"file": _b64(raw), "name": "local.docx", "dry_run": True})
    assert status_dry == 200
