"""Tests for P0 Independent Review Corrective Round.

Verifies:
- A06: Canonical-only Pipeline.clean() for /clean, SHA256 invariant, no dual cleaner
- A08: /clean/batch routes through canonical pipeline, parity with /clean and /batch
- A07: Normal text clean never requires Layer B, zero network calls
- A11: Real data-descriptor / bit-3 handling for DOCX, XLSX, and PPTX
- A17: XLSX & PPTX exact mutation identity resolution (duplicate text witnesses & fail closed)
- A13: Truthful DOCX surface coverage (visible_field_results, instrText, delText)
- A02: DocxMutationPlan true immutability after freeze()
- A18: UI truthfulness, dynamic versioning from capabilities, and Dry Run semantics
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import socket
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pytest

from service.scripts.docx.detector import DocxDetector, W_NS
from service.scripts.docx.mutation_plan import (
    DocxMutationPlan,
    MetadataFieldScrubMutation,
    PartDropMutation,
    TextCodepointMutation,
)
from service.scripts.docx.package import DocxPackage
from service.scripts.docx.cleaner import clean_docx_lossless
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import PipelineStatus, ProcessingMode
from service.scripts.pptx.cleaner import clean_pptx_lossless
from service.scripts.pptx.exceptions import PptxPatchError
from service.scripts.pptx.models import PptxTextMutation
from service.scripts.pptx.mutation_plan import PptxMutationPlan
from service.scripts.pptx.package import PptxPackage
from service.scripts.pptx.patcher import PptxPatcher
import http.client
import threading
import server
from service.scripts.xlsx.cleaner import clean_xlsx_lossless
from service.scripts.xlsx.exceptions import XlsxPatchError
from service.scripts.xlsx.models import XlsxTextMutation
from service.scripts.xlsx.mutation_plan import XlsxMutationPlan
from service.scripts.xlsx.package import XlsxPackage
from service.scripts.xlsx.patcher import XlsxPatcher

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def _build_bit3_zip(orig_bytes: bytes, target_members: list[str]) -> bytes:
    """Construct a real ZIP archive with bit 3 set and trailing data descriptor for target members."""
    zf_in = zipfile.ZipFile(io.BytesIO(orig_bytes), "r")
    out = io.BytesIO()
    cd_entries = []

    for info in zf_in.infolist():
        raw_uncomp = zf_in.open(info).read()
        comp_obj = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
        cdata = comp_obj.compress(raw_uncomp) + comp_obj.flush()
        crc = zlib.crc32(raw_uncomp) & 0xFFFFFFFF
        usize = len(raw_uncomp)
        csize = len(cdata)

        name_bytes = info.filename.encode("utf-8")
        loc_off = out.tell()

        is_target = info.filename in target_members
        flags = info.flag_bits
        if is_target:
            flags |= 0x08  # bit 3 set: crc/sizes are zero in local header
            loc_hdr = struct.pack(
                "<IHHHHHIIIHH",
                0x04034B50,
                20,
                flags,
                8,
                0,
                0x21,
                0,  # crc zero
                0,  # csize zero
                0,  # usize zero
                len(name_bytes),
                0,
            ) + name_bytes
            out.write(loc_hdr)
            out.write(cdata)
            # data descriptor with PK\x07\x08 signature
            desc = struct.pack("<4sIII", b"PK\x07\x08", crc, csize, usize)
            out.write(desc)
        else:
            loc_hdr = struct.pack(
                "<IHHHHHIIIHH",
                0x04034B50,
                20,
                flags,
                8,
                0,
                0x21,
                crc,
                csize,
                usize,
                len(name_bytes),
                0,
            ) + name_bytes
            out.write(loc_hdr)
            out.write(cdata)

        cd_hdr = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            flags,
            8,
            0,
            0x21,
            crc,
            csize,
            usize,
            len(name_bytes),
            0,
            0,
            0,
            0,
            0,
            loc_off,
        ) + name_bytes
        cd_entries.append(cd_hdr)

    cd_start = out.tell()
    for cd in cd_entries:
        out.write(cd)
    cd_size = out.tell() - cd_start
    eocd = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        len(cd_entries),
        len(cd_entries),
        cd_size,
        cd_start,
        0,
    )
    out.write(eocd)
    return out.getvalue()


# -----------------------------------------------------------------------------
# A06: Canonical-only Pipeline.clean() for /clean & SHA256 Invariant
# -----------------------------------------------------------------------------

def test_a06_clean_endpoint_canonical_sha256_invariant(conn):
    """Verify POST /clean returns bytes matching report.output.sha256 exactly."""
    test_cases = [
        ("sample.txt", "Text with \u200b watermark".encode("utf-8")),
        ("doc.docx", (REPO_ROOT / "tests/fixtures/docx_body_carriers/carrier_zwsp.docx").read_bytes()),
        ("sheet.xlsx", (REPO_ROOT / "tests/fixtures/xlsx_lossless/carrier_shared_string.xlsx").read_bytes()),
        ("slides.pptx", (REPO_ROOT / "tests/fixtures/pptx_lossless/carrier_slide_text.pptx").read_bytes()),
    ]

    for filename, raw_bytes in test_cases:
        b64_in = base64.b64encode(raw_bytes).decode("ascii")
        status, data = _post(conn, "/clean", {"name": filename, "file": b64_in, "mode": "SAFE"})
        assert status == 200, f"Failed cleaning {filename}: {data}"

        assert data["ok"] is True
        assert "cleaned" in data
        returned_bytes = base64.b64decode(data["cleaned"])
        actual_sha = hashlib.sha256(returned_bytes).hexdigest()

        report_sha = data["report"]["output"]["sha256"]
        assert actual_sha == report_sha, (
            f"SHA256 mismatch for {filename}: returned bytes {actual_sha} != report {report_sha}"
        )


# -----------------------------------------------------------------------------
# A08: /clean/batch and /batch Parity with /clean
# -----------------------------------------------------------------------------

def test_a08_batch_parity_with_canonical_pipeline(conn):
    """Verify /clean, /clean/batch, and /batch operation=clean yield identical bytes and hashes."""
    raw_bytes = (REPO_ROOT / "tests/fixtures/pptx_lossless/carrier_slide_text.pptx").read_bytes()
    b64_in = base64.b64encode(raw_bytes).decode("ascii")

    # 1. Single /clean
    status_single, single_data = _post(conn, "/clean", {"name": "test.pptx", "file": b64_in, "mode": "SAFE"})
    assert status_single == 200
    single_bytes = base64.b64decode(single_data["cleaned"])
    single_sha = hashlib.sha256(single_bytes).hexdigest()

    # 2. Compatibility /clean/batch
    status_compat, compat_data = _post(
        conn,
        "/clean/batch",
        {"files": [{"name": "test.pptx", "file": b64_in}], "mode": "SAFE"},
    )
    assert status_compat == 200
    assert compat_data["results"][0]["ok"] is True
    compat_bytes = base64.b64decode(compat_data["results"][0]["cleaned"])
    compat_sha = hashlib.sha256(compat_bytes).hexdigest()

    # 3. Canonical /batch
    status_batch, batch_data = _post(
        conn,
        "/batch",
        {
            "operation": "clean",
            "files": [{"name": "test.pptx", "file": b64_in}],
            "mode": "SAFE",
        },
    )
    assert status_batch == 200
    batch_bytes = base64.b64decode(batch_data["outputs"][0]["content_base64"])
    batch_sha = hashlib.sha256(batch_bytes).hexdigest()

    # Assert exact byte parity across all three endpoints
    assert single_sha == compat_sha == batch_sha
    assert single_bytes == compat_bytes == batch_bytes


# -----------------------------------------------------------------------------
# A07: Normal Clean Must Never Require Layer B & Zero Network Calls
# -----------------------------------------------------------------------------

def test_a07_normal_clean_never_requires_layer_b(conn, monkeypatch):
    """Verify normal text cleaning performs Layer A only without requiring Layer B rewrite."""
    # Guard against any outbound non-local socket activity
    orig_connect = socket.socket.connect
    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost"):
            raise RuntimeError(f"Zero-network violation: outbound socket call to {host} attempted")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    text_input = "Sample plain text without AI metadata or invisible chars"
    b64_in = base64.b64encode(text_input.encode("utf-8")).decode("ascii")

    # Single /clean with empty options
    status, data = _post(conn, "/clean", {"name": "test.txt", "file": b64_in, "options": {}})
    assert status == 200
    assert data["ok"] is True
    assert "Layer B rewrite is required" not in str(data)

    # Batch clean
    status_batch, data_batch = _post(
        conn,
        "/clean/batch",
        {"files": [{"name": "test.txt", "file": b64_in}], "options": {}},
    )
    assert status_batch == 200
    assert status_batch == 200
    assert "Layer B rewrite is required" not in str(data_batch)


# -----------------------------------------------------------------------------
# A11: Real Data-Descriptor / Bit-3 Testing across DOCX, XLSX, PPTX
# -----------------------------------------------------------------------------

def test_a11_real_bit3_data_descriptor_docx():
    """Verify real bit-3 source DOCX has bit 3 cleared on modified entry and preserved on untouched entry."""
    fixture_path = REPO_ROOT / "tests/fixtures/docx_body_carriers/carrier_zwsp.docx"
    assert fixture_path.exists(), f"Fixture missing: {fixture_path}"

    orig_docx = fixture_path.read_bytes()
    # word/document.xml is modified, docProps/app.xml is untouched
    bit3_docx = _build_bit3_zip(orig_docx, ["word/document.xml", "docProps/app.xml"])

    # Verify bit 3 before cleaning
    pkg_in = DocxPackage(bit3_docx)
    assert pkg_in.zip_infos["word/document.xml"].flag_bits & 0x08 != 0
    assert pkg_in.zip_infos["docProps/app.xml"].flag_bits & 0x08 != 0

    cleaned_bytes, rep = clean_docx_lossless(bit3_docx, {"mode": "SAFE", "also_layer_a_text": True})
    assert rep["changed"] is True

    pkg_out = DocxPackage(cleaned_bytes)
    # Modified entry MUST have bit 3 cleared
    assert (pkg_out.zip_infos["word/document.xml"].flag_bits & 0x08) == 0
    # Untouched entry MUST preserve bit 3 and descriptor
    assert (pkg_out.zip_infos["docProps/app.xml"].flag_bits & 0x08) != 0


def test_a11_real_bit3_data_descriptor_xlsx():
    """Verify real bit-3 source XLSX has bit 3 cleared on modified entry and preserved on untouched entry."""
    fixture_path = REPO_ROOT / "tests/fixtures/xlsx_lossless/carrier_shared_string.xlsx"
    assert fixture_path.exists(), f"Fixture missing: {fixture_path}"

    orig_xlsx = fixture_path.read_bytes()
    # xl/sharedStrings.xml is modified, xl/workbook.xml is untouched
    bit3_xlsx = _build_bit3_zip(orig_xlsx, ["xl/sharedStrings.xml", "xl/workbook.xml"])

    pkg_in = XlsxPackage(bit3_xlsx)
    assert pkg_in.zip_infos["xl/sharedStrings.xml"].flag_bits & 0x08 != 0
    assert pkg_in.zip_infos["xl/workbook.xml"].flag_bits & 0x08 != 0

    cleaned_bytes, rep = clean_xlsx_lossless(bit3_xlsx, {"mode": "SAFE"})
    assert rep["changed"] is True

    pkg_out = XlsxPackage(cleaned_bytes)
    assert (pkg_out.zip_infos["xl/sharedStrings.xml"].flag_bits & 0x08) == 0
    assert (pkg_out.zip_infos["xl/workbook.xml"].flag_bits & 0x08) != 0


def test_a11_real_bit3_data_descriptor_pptx():
    """Verify real bit-3 source PPTX has bit 3 cleared on modified entry and preserved on untouched entry."""
    fixture_path = REPO_ROOT / "tests/fixtures/pptx_lossless/carrier_slide_text.pptx"
    assert fixture_path.exists(), f"Fixture missing: {fixture_path}"

    orig_pptx = fixture_path.read_bytes()
    # ppt/slides/slide1.xml is modified, ppt/presentation.xml is untouched
    bit3_pptx = _build_bit3_zip(orig_pptx, ["ppt/slides/slide1.xml", "ppt/presentation.xml"])

    pkg_in = PptxPackage(bit3_pptx)
    assert pkg_in.zip_infos["ppt/slides/slide1.xml"].flag_bits & 0x08 != 0
    assert pkg_in.zip_infos["ppt/presentation.xml"].flag_bits & 0x08 != 0

    cleaned_bytes, rep = clean_pptx_lossless(bit3_pptx, {"mode": "SAFE"})
    assert rep["changed"] is True

    pkg_out = PptxPackage(cleaned_bytes)
    assert (pkg_out.zip_infos["ppt/slides/slide1.xml"].flag_bits & 0x08) == 0
    assert (pkg_out.zip_infos["ppt/presentation.xml"].flag_bits & 0x08) != 0


# -----------------------------------------------------------------------------
# A17: Remove Content-Global Fallback & Enforce Exact Mutation Identity
# -----------------------------------------------------------------------------

def test_a17_xlsx_duplicate_text_witness():
    """Verify XLSX patcher modifies only the targeted occurrence when identical text exists."""
    fixture_path = REPO_ROOT / "tests/fixtures/xlsx_lossless/carrier_shared_string.xlsx"
    assert fixture_path.exists(), f"Fixture missing: {fixture_path}"

    orig_bytes = fixture_path.read_bytes()
    pkg = XlsxPackage(orig_bytes)

    # Construct sharedStrings with two identical strings
    sst_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">\n'
        '  <si><t>Duplicate Secret</t></si>\n'
        '  <si><t>Duplicate Secret</t></si>\n'
        '</sst>'
    )
    pkg_dup = XlsxPackage(pkg.rebuild({"xl/sharedStrings.xml": sst_xml.encode("utf-8")}))

    # Plan targets ONLY si_idx=0
    plan = XlsxMutationPlan()
    plan.text_mutations.append(
        XlsxTextMutation(
            part_name="xl/sharedStrings.xml",
            location="sst[0]",
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            original_text="Duplicate Secret",
            replacement_text="Cleaned Secret",
            si_idx=0,
        )
    )

    patcher = XlsxPatcher(pkg_dup, plan)
    patched_bytes = patcher.apply()

    pkg_res = XlsxPackage(patched_bytes)
    res_sst = pkg_res.get_member("xl/sharedStrings.xml").decode("utf-8")

    assert "<si><t>Cleaned Secret</t></si>" in res_sst
    assert "<si><t>Duplicate Secret</t></si>" in res_sst

    # Fail closed witness: if planned identity cannot be resolved, raise XlsxPatchError
    plan_invalid = XlsxMutationPlan()
    plan_invalid.text_mutations.append(
        XlsxTextMutation(
            part_name="xl/sharedStrings.xml",
            location="sst[999]",
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            original_text="Duplicate Secret",
            replacement_text="Cleaned Secret",
            si_idx=999,  # non-existent
        )
    )
    with pytest.raises(XlsxPatchError):
        XlsxPatcher(pkg_dup, plan_invalid).apply()


def test_a17_pptx_duplicate_text_witness():
    """Verify PPTX patcher modifies only the targeted run when identical text exists."""
    fixture_path = REPO_ROOT / "tests/fixtures/pptx_lossless/carrier_slide_text.pptx"
    assert fixture_path.exists(), f"Fixture missing: {fixture_path}"

    orig_bytes = fixture_path.read_bytes()
    pkg = PptxPackage(orig_bytes)

    # Craft slide XML with two shapes having identical text
    slide_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">\n'
        '  <p:cSld><p:spTree>\n'
        '    <p:sp><p:nvSpPr><p:cNvPr id="10" name="Title"/></p:nvSpPr>\n'
        '      <p:txBody><a:p><a:r><a:t>Duplicate Run</a:t></a:r></a:p></p:txBody>\n'
        '    </p:sp>\n'
        '    <p:sp><p:nvSpPr><p:cNvPr id="20" name="Subtitle"/></p:nvSpPr>\n'
        '      <p:txBody><a:p><a:r><a:t>Duplicate Run</a:t></a:r></a:p></p:txBody>\n'
        '    </p:sp>\n'
        '  </p:spTree></p:cSld>\n'
        '</p:sld>'
    )
    pkg_dup = PptxPackage(pkg.build_patched_package({"ppt/slides/slide1.xml": slide_xml.encode("utf-8")}))

    # Plan targets ONLY shape id="10"
    plan = PptxMutationPlan()
    plan.text_mutations.append(
        PptxTextMutation(
            part_name="ppt/slides/slide1.xml",
            location="shape[10]",
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            shape_id="10",
            p_idx=1,
            r_idx=1,
            t_idx=1,
            original_text="Duplicate Run",
            replacement_text="Cleaned Run",
        )
    )

    patcher = PptxPatcher(pkg_dup, plan)
    patched_bytes = patcher.apply()

    pkg_res = PptxPackage(patched_bytes)
    res_slide = pkg_res.get_member("ppt/slides/slide1.xml").decode("utf-8")

    # Shape 10 was modified to Cleaned Run
    assert "Cleaned Run" in res_slide
    # Shape 20 remained untouched with Duplicate Run
    assert "Duplicate Run" in res_slide

    # Fail closed witness: if planned identity cannot be resolved, raise PptxPatchError
    plan_invalid = PptxMutationPlan()
    plan_invalid.text_mutations.append(
        PptxTextMutation(
            part_name="ppt/slides/slide1.xml",
            location="shape[999]",
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            shape_id="999",  # non-existent
            p_idx=0,
            r_idx=0,
            t_idx=0,
            original_text="Duplicate Run",
            replacement_text="Cleaned Run",
        )
    )
    with pytest.raises(PptxPatchError):
        PptxPatcher(pkg_dup, plan_invalid).apply()


# -----------------------------------------------------------------------------
# A13: Truthful Surface Coverage Reporting
# -----------------------------------------------------------------------------

def test_a13_surface_coverage_truthfulness():
    """Verify separate reporting of visible_field_results, instrText, and delText."""
    fixture_path = REPO_ROOT / "tests/fixtures/docx_body_carriers/carrier_zwsp.docx"
    assert fixture_path.exists()
    pkg = DocxPackage(fixture_path.read_bytes())
    detector = DocxDetector(pkg, {"mode": "SAFE"})
    plan = detector.build_plan()

    assert plan.surface_coverage["visible_field_results"] == "CHECKED"
    assert plan.surface_coverage["field_instructions_instrText"] == "NOT_CHECKED"
    assert plan.surface_coverage["tracked_deletions_delText"] == "NOT_CHECKED"


# -----------------------------------------------------------------------------
# A02: DocxMutationPlan Immutability After freeze()
# -----------------------------------------------------------------------------

def test_a02_docx_mutation_plan_immutability():
    """Verify DocxMutationPlan collections and attributes cannot be mutated after freeze()."""
    plan = DocxMutationPlan()
    plan.text_mutations.append(
        TextCodepointMutation("word/document.xml", 0, 0, 0, 0x200B, "ZERO WIDTH SPACE", 0)
    )
    plan.surface_coverage["body_document"] = "CHECKED"
    plan.freeze()

    assert plan._is_frozen is True

    # 1. Collections cannot be appended to or removed from
    with pytest.raises(AttributeError):
        plan.text_mutations.append(None)  # type: ignore

    # 2. Surface mapping cannot be modified
    with pytest.raises(TypeError):
        plan.surface_coverage["new_key"] = "CHECKED"  # type: ignore

    # 3. Attributes cannot be reassigned
    with pytest.raises(TypeError):
        plan.text_mutations = []

    with pytest.raises(TypeError):
        plan.surface_coverage = {}

    with pytest.raises(TypeError):
        plan._is_frozen = False

    # 4. Attributes cannot be deleted
    with pytest.raises(TypeError):
        del plan.text_mutations


# -----------------------------------------------------------------------------
# A18: Truthful UI Dynamic Branding and Dry Run Semantics
# -----------------------------------------------------------------------------

def test_a18_ui_branding_and_dry_run_semantics():
    """Verify HTML and JS do not contain stale v2.1 or absolute lossless claims, and Dry Run semantics are exact."""
    html_content = (REPO_ROOT / "service/web/index.html").read_text(encoding="utf-8")
    js_content = (REPO_ROOT / "service/web/app.js").read_text(encoding="utf-8")

    # No hardcoded v2.1 user-facing branding
    assert "ClearMark v2.1" not in html_content
    assert "ClearMark v2.1" not in js_content

    # No absolute lossless claims
    assert "Bảo toàn Lossless" not in html_content
    assert "bảo toàn tuyệt đối" not in html_content
    assert "Lossless 100% trung thực" not in js_content

    # Grounded fidelity wording
    assert "Kiểm chứng Fidelity" in html_content or "Kiểm chứng fidelity" in html_content
    assert "KIỂM CHỨNG FIDELITY: PASS" in html_content
    assert "Không phát hiện thay đổi ngoài phạm vi cho phép." in js_content

    # Dry Run label exactness
    assert "Xem trước tất cả" in js_content
    assert "Xem trước" in js_content
    assert "không có tệp kết quả nào được tạo" in js_content
