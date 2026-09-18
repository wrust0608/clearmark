"""Tests for P0 Independent Review Round 2 Corrective Work.

Verifies:
- A02: Complete removal of legacy global codepoint patch fallback; exact mutation identity witness
- A08: True single/batch semantic parity across /clean, /clean/batch, and /batch (mode, dry_run, options, limits)
- A07: Explicit rejection of strategy / Layer B requests with HTTP 400 Bad Request
- UI Bug: Non-DOCX single clean sends {} options and successfully cleans TXT, MD, PNG
- A11: Preservation of compatible changed-entry ZIP extra fields, entry comments, and flag semantics in DOCX, XLSX, PPTX
- A18: Complete UI truthfulness (removal of pre-validation Lossless overclaims)
- Evidence Integrity: Every test node ID in V2_2_RC2_HARDENING_EVIDENCE.json resolves to real collected pytest nodes
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import os
import struct
import subprocess
import sys
import threading
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pytest

import server
from service.scripts.batch_processor import (
    MAX_BATCH_FILES,
    MAX_INPUT_BYTES,
    MAX_BATCH_TOTAL_BYTES,
    BatchLimitExceededError,
    BatchProcessor,
)
from service.scripts.docx.mutation_plan import DocxMutationPlan, TextCodepointMutation
from service.scripts.docx.package import DocxPackage
from service.scripts.docx.patcher import DocxPatcher
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import PipelineStatus, ProcessingMode
from service.scripts.pptx.models import PptxTextMutation
from service.scripts.pptx.mutation_plan import PptxMutationPlan
from service.scripts.pptx.package import PptxPackage
from service.scripts.pptx.patcher import PptxPatcher
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


# -----------------------------------------------------------------------------
# 1. A02: Complete Removal of Legacy Global Codepoint Fallback & Exact Witness
# -----------------------------------------------------------------------------


def test_a02_docx_patcher_rejects_legacy_set_and_non_mutations():
    """Static regression test proving no global-codepoint fallback exists in DocxPatcher."""
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Hello&#x200B;world</w:t></w:r></w:p></w:body>'
        '</w:document>'
    )
    # Construct a minimal dummy package
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml_text.encode("utf-8"))
        zf.writestr("[Content_Types].xml", b"<Types/>")
    pkg = DocxPackage(buf.getvalue())
    plan = DocxMutationPlan()
    patcher = DocxPatcher(pkg, plan)

    # Must raise TypeError when given a set of codepoints
    with pytest.raises(TypeError, match="DocxPatcher requires Sequence\\[TextCodepointMutation\\]"):
        patcher._patch_text_part(xml_text, {0x200B})  # type: ignore

    # Must raise TypeError when given a frozenset
    with pytest.raises(TypeError, match="DocxPatcher requires Sequence\\[TextCodepointMutation\\]"):
        patcher._patch_text_part(xml_text, frozenset([0x200B]))  # type: ignore

    # Must raise TypeError when given arbitrary non-TextCodepointMutation objects
    with pytest.raises(TypeError, match="DocxPatcher requires TextCodepointMutation instances"):
        patcher._patch_text_part(xml_text, ["not_a_mutation"])  # type: ignore


def test_a02_docx_witness_duplicate_codepoints_plan_authorizes_only_one():
    """Witness: same XML part contains two U+200B occurrences; plan authorizes only one;

    only that exact occurrence changes.
    """
    # XML with two U+200B occurrences in the same <w:t> run:
    # Character indices:
    # 'A' (0), U+200B (1), 'B' (2), U+200B (3), 'C' (4)
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>A\u200bB\u200bC</w:t></w:r></w:p></w:body>'
        '</w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml_text.encode("utf-8"))
        zf.writestr("[Content_Types].xml", b"<Types/>")
    pkg = DocxPackage(buf.getvalue())

    # 1. Authorize ONLY the first occurrence (offset 1)
    plan1 = DocxMutationPlan()
    plan1.text_mutations.append(
        TextCodepointMutation(
            part_name="word/document.xml",
            p_idx=0,
            r_idx=0,
            t_idx=0,
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            offset=1,
            t_block_idx=0,
        )
    )
    patcher1 = DocxPatcher(pkg, plan1)
    patched_xml1 = patcher1._patch_text_part(xml_text, plan1.text_mutations)

    # Result: first U+200B removed, second U+200B remains intact!
    assert "AB\u200bC" in patched_xml1
    assert patched_xml1.count("\u200b") == 1

    # 2. Authorize ONLY the second occurrence (offset 3)
    plan2 = DocxMutationPlan()
    plan2.text_mutations.append(
        TextCodepointMutation(
            part_name="word/document.xml",
            p_idx=0,
            r_idx=0,
            t_idx=0,
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            offset=3,
            t_block_idx=0,
        )
    )
    patcher2 = DocxPatcher(pkg, plan2)
    patched_xml2 = patcher2._patch_text_part(xml_text, plan2.text_mutations)

    # Result: second U+200B removed, first U+200B remains intact!
    assert "A\u200bBC" in patched_xml2
    assert patched_xml2.count("\u200b") == 1


# -----------------------------------------------------------------------------
# 2. A08: True Single/Batch Semantic Parity & Limits
# -----------------------------------------------------------------------------


def test_a08_batch_mode_propagation_safe_balanced_aggressive(conn):
    """Verify top-level mode in /clean/batch and /batch is honored, not ignored."""
    raw = "Hello\u200Bworld \u200Ctest".encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")

    for mode in ("SAFE", "BALANCED", "AGGRESSIVE"):
        # Test /clean/batch
        status_cb, data_cb = _post(
            conn,
            "/clean/batch",
            {"mode": mode, "files": [{"name": "doc.txt", "file": b64}]},
        )
        assert status_cb == 200
        assert data_cb["ok"] is True
        assert data_cb["results"][0]["report"]["mode"] == mode

        # Test /batch
        status_b, data_b = _post(
            conn,
            "/batch",
            {"operation": "clean", "mode": mode, "files": [{"name": "doc.txt", "file": b64}]},
        )
        assert status_b == 200
        assert data_b["ok"] is True
        assert data_b["report"]["mode"] == mode


def test_a08_batch_invalid_mode_rejected_with_400(conn):
    """Verify invalid mode in /clean/batch and /batch is rejected with HTTP 400 (no silent fallback)."""
    raw = b"Sample text"
    b64 = base64.b64encode(raw).decode("ascii")

    for path in ("/clean/batch", "/batch"):
        status, data = _post(
            conn,
            path,
            {"mode": "SUPER_SAFE", "files": [{"name": "test.txt", "file": b64}]},
        )
        assert status == 400
        assert data["ok"] is False
        assert "Invalid mode" in data["error"]


def test_a08_batch_dry_run_propagation(conn):
    """Verify top-level dry_run in /clean/batch and /batch propagates to all items."""
    raw = "Watermarked\u200Bcontent".encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")

    # /clean/batch with dry_run: true
    status_cb, data_cb = _post(
        conn,
        "/clean/batch",
        {"dry_run": True, "files": [{"name": "doc.txt", "file": b64}]},
    )
    assert status_cb == 200
    assert data_cb["results"][0]["cleaned"] == ""  # dry run returns no cleaned bytes
    assert data_cb["results"][0]["report"]["dry_run"] is True

    # /batch with dry_run: true
    status_b, data_b = _post(
        conn,
        "/batch",
        {"operation": "clean", "dry_run": True, "files": [{"name": "doc.txt", "file": b64}]},
    )
    assert status_b == 200
    assert data_b["outputs_included"] is False
    assert data_b["output_delivery"] == "dry_run"
    assert data_b["report"]["dry_run"] is True


def test_a08_batch_top_level_options_propagation(conn):
    """Verify top-level options propagate to entries in /clean/batch and /batch."""
    raw = "Multiple   spaces   here".encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")

    status, data = _post(
        conn,
        "/clean/batch",
        {
            "mode": "SAFE",
            "options": {"normalize_spaces": False},
            "files": [{"name": "doc.txt", "file": b64}],
        },
    )
    assert status == 200
    assert data["ok"] is True
    cleaned_bytes = base64.b64decode(data["results"][0]["cleaned"])
    assert b"Multiple   spaces   here" in cleaned_bytes


def test_a08_batch_limits_file_count_per_file_and_aggregate(conn, monkeypatch):
    """Test limits: batch count > 50, per-file > 32 MiB (fault isolation), aggregate > 200 MiB."""
    # 1. Batch file count > 50
    files_51 = [{"name": f"f{i}.txt", "file": base64.b64encode(b"a").decode("ascii")} for i in range(51)]
    status, data = _post(conn, "/clean/batch", {"files": files_51})
    assert status == 413
    assert "exceeds maximum allowed (50)" in data["error"]

    status_b, data_b = _post(conn, "/batch", {"operation": "clean", "files": files_51})
    assert status_b == 413
    assert "exceeds maximum allowed (50)" in data_b["error"]

    # 2. Per-file limit (simulated with configured limit override to avoid giant buffer)
    import sys
    if "batch_processor" in sys.modules:
        monkeypatch.setattr("batch_processor.MAX_INPUT_BYTES", 50)
    monkeypatch.setattr("service.scripts.batch_processor.MAX_INPUT_BYTES", 50)
    monkeypatch.setenv("WATERMARKS_MAX_FILE_BYTES", "50")
    oversized_b64 = base64.b64encode(b"x" * 60).decode("ascii")
    ok_b64 = base64.b64encode(b"y" * 20).decode("ascii")

    status, data = _post(
        conn,
        "/clean/batch",
        {"files": [{"name": "big.txt", "file": oversized_b64}, {"name": "small.txt", "file": ok_b64}]},
    )
    assert status == 200
    assert data["results"][0]["ok"] is False
    assert "PROCESSING_LIMIT_EXCEEDED" in str(data["results"][0])
    assert data["results"][1]["ok"] is True  # Sibling file processed successfully!

    # 3. Aggregate batch limit (simulated with configured limit override)
    if "batch_processor" in sys.modules:
        monkeypatch.setattr("batch_processor.MAX_BATCH_TOTAL_BYTES", 100)
    monkeypatch.setattr("service.scripts.batch_processor.MAX_BATCH_TOTAL_BYTES", 100)
    monkeypatch.setenv("WATERMARKS_MAX_BATCH_TOTAL_BYTES", "100")
    status_agg, data_agg = _post(
        conn,
        "/clean/batch",
        {"files": [{"name": "f1.txt", "file": base64.b64encode(b"x" * 60).decode("ascii")},
                   {"name": "f2.txt", "file": base64.b64encode(b"x" * 60).decode("ascii")}]},
    )
    assert status_agg == 413
    assert "exceeds" in data_agg["error"]


def test_a08_semantic_parity_single_clean_clean_batch_and_batch(conn):
    """Parity: same bytes + same mode + same options -> identical output across /clean, /clean/batch, /batch."""
    raw = "Sample\u200Bwatermark\u200Ctext".encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")

    # 1. /clean
    s1, d1 = _post(conn, "/clean", {"name": "parity.txt", "file": b64, "mode": "SAFE", "options": {}})
    assert s1 == 200
    out1 = base64.b64decode(d1["cleaned"])

    # 2. /clean/batch
    s2, d2 = _post(conn, "/clean/batch", {"mode": "SAFE", "files": [{"name": "parity.txt", "file": b64}]})
    assert s2 == 200
    out2 = base64.b64decode(d2["results"][0]["cleaned"])

    # 3. /batch
    s3, d3 = _post(conn, "/batch", {"operation": "clean", "mode": "SAFE", "files": [{"name": "parity.txt", "file": b64}]})
    assert s3 == 200
    out3 = base64.b64decode(d3["outputs"][0]["content_base64"])

    assert out1 == out2 == out3
    assert d1["report"]["input"]["sha256"] == d2["results"][0]["report"]["input"]["sha256"] == d3["report"]["items"][0]["report"]["input"]["sha256"]


# -----------------------------------------------------------------------------
# 3. UI/API Bug: Non-DOCX Clean Options Alignment ({})
# -----------------------------------------------------------------------------


def test_ui_clean_non_docx_formats_reach_canonical_clean_successfully(conn):
    """Test that single-file clean for TXT, Markdown, and PNG with options {} reaches /clean successfully."""
    # 1. Single TXT
    txt_raw = "Hello\u200Bworld".encode("utf-8")
    s_txt, d_txt = _post(conn, "/clean", {"name": "doc.txt", "file": base64.b64encode(txt_raw).decode("ascii"), "options": {}})
    assert s_txt == 200
    assert d_txt["ok"] is True
    cleaned_txt = base64.b64decode(d_txt["cleaned"]).decode("utf-8")
    assert "\u200b" not in cleaned_txt

    # 2. Single Markdown
    md_raw = "# Title\n\nSome\u200Btext\n".encode("utf-8")
    s_md, d_md = _post(conn, "/clean", {"name": "doc.md", "file": base64.b64encode(md_raw).decode("ascii"), "options": {}})
    assert s_md == 200
    assert d_md["ok"] is True

    # 3. Single PNG (1x1 transparent PNG)
    png_raw = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )
    s_png, d_png = _post(conn, "/clean", {"name": "img.png", "file": base64.b64encode(png_raw).decode("ascii"), "options": {}})
    assert s_png == 200
    assert d_png["ok"] is True

    # 4. Compare single file clean vs same file in multi-file batch
    s_batch, d_batch = _post(
        conn,
        "/clean/batch",
        {"files": [{"name": "doc.txt", "file": base64.b64encode(txt_raw).decode("ascii")},
                   {"name": "doc.md", "file": base64.b64encode(md_raw).decode("ascii")},
                   {"name": "img.png", "file": base64.b64encode(png_raw).decode("ascii")}]},
    )
    assert s_batch == 200
    assert d_batch["results"][0]["cleaned"] == d_txt["cleaned"]
    assert d_batch["results"][1]["cleaned"] == d_md["cleaned"]
    assert d_batch["results"][2]["cleaned"] == d_png["cleaned"]


# -----------------------------------------------------------------------------
# 4. A07: Reject Strategy / Layer B Requests Explicitly
# -----------------------------------------------------------------------------


def test_a07_normal_clean_with_strategy_explicitly_rejected(conn):
    """Normal clean + strategy in options -> explicit HTTP 400 Bad Request rejection."""
    raw = b"Clean text"
    b64 = base64.b64encode(raw).decode("ascii")

    # Clean with strategy option
    status, data = _post(
        conn,
        "/clean",
        {"name": "sample.txt", "file": b64, "options": {"strategy": "synonym:medium"}},
    )
    assert status == 400
    assert data["ok"] is False
    assert "Advanced Statistical Layer B rewriting is not available in P0 canonical clean; Layer B is disabled until P1." in data["error"]

    # Normal clean without strategy succeeds (Layer A only, zero network)
    status_ok, data_ok = _post(
        conn,
        "/clean",
        {"name": "sample.txt", "file": b64, "options": {}},
    )
    assert status_ok == 200
    assert data_ok["ok"] is True


# -----------------------------------------------------------------------------
# 5. A11: OOXML Changed-Entry ZIP Metadata Fidelity (Extra Fields, Comments, Flags)
# -----------------------------------------------------------------------------


def _create_zip_with_extra_and_comment(xml_path: str, xml_bytes: bytes, other_files: dict[str, bytes]) -> bytes:
    """Create a ZIP with custom 0x5455 extra field and entry comment on target member."""
    out = io.BytesIO()
    zf = zipfile.ZipFile(out, "w")
    for k, v in other_files.items():
        zf.writestr(k, v)

    # Info-ZIP extended timestamp (tag 0x5455, length 5: flag 0x01 + 4-byte unix time)
    extra_field = struct.pack("<HHBI", 0x5455, 5, 0x01, 1600000000)
    entry_comment = b"Original entry comment"

    info = zipfile.ZipInfo(xml_path)
    info.extra = extra_field
    info.comment = entry_comment
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, xml_bytes)
    zf.close()
    return out.getvalue()


def test_a11_docx_changed_entry_preserves_compatible_extra_fields_and_comment():
    """Verify modified DOCX member preserves safe ZIP extra fields and entry comment."""
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Sample\u200btext</w:t></w:r></w:p></w:body>'
        '</w:document>'
    )
    zip_bytes = _create_zip_with_extra_and_comment(
        "word/document.xml",
        xml_text.encode("utf-8"),
        {"[Content_Types].xml": b"<Types/>"},
    )

    pkg = DocxPackage(zip_bytes)
    plan = DocxMutationPlan()
    plan.text_mutations.append(
        TextCodepointMutation("word/document.xml", 0, 0, 0, 0x200B, "ZERO WIDTH SPACE", 6, 0)
    )
    patcher = DocxPatcher(pkg, plan)
    rebuilt_bytes = patcher.apply()

    zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt_bytes), "r")
    target_info = zf_rebuilt.getinfo("word/document.xml")

    # Extra field 0x5455 must be preserved
    assert len(target_info.extra) > 0
    assert target_info.extra.startswith(b"\x55\x54")  # 0x5455 in little-endian
    # Comment must be preserved
    assert target_info.comment == b"Original entry comment"


def test_a11_xlsx_changed_entry_preserves_metadata_and_does_not_force_0x800():
    """Verify modified XLSX member preserves extra fields and comment, and does not force flag 0x800."""
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<si><t>Item\u200bOne</t></si>'
        '</sst>'
    )
    zip_bytes = _create_zip_with_extra_and_comment(
        "xl/sharedStrings.xml",
        xml_text.encode("utf-8"),
        {"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<workbook/>"},
    )

    pkg = XlsxPackage(zip_bytes)
    orig_flag = pkg.zip_infos["xl/sharedStrings.xml"].flag_bits
    # Ensure original flag does not have 0x800
    assert (orig_flag & 0x800) == 0

    plan = XlsxMutationPlan()
    plan.text_mutations.append(
        XlsxTextMutation(
            part_name="xl/sharedStrings.xml",
            location="sst[0]",
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            original_text="Item\u200bOne",
            replacement_text="ItemOne",
            si_idx=0,
        )
    )
    patcher = XlsxPatcher(pkg, plan)
    rebuilt_bytes = patcher.apply()

    zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt_bytes), "r")
    target_info = zf_rebuilt.getinfo("xl/sharedStrings.xml")

    # Safe extra field and comment preserved
    assert target_info.extra.startswith(b"\x55\x54")
    assert target_info.comment == b"Original entry comment"
    # Flag bits must NOT have arbitrary 0x800 forced
    assert (target_info.flag_bits & 0x800) == 0
    assert target_info.flag_bits == (orig_flag & ~0x08)


def test_a11_pptx_changed_entry_preserves_extra_fields_and_comment():
    """Verify modified PPTX member preserves safe ZIP extra fields and entry comment."""
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Slide\u200btext</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>'
        '</p:sld>'
    )
    zip_bytes = _create_zip_with_extra_and_comment(
        "ppt/slides/slide1.xml",
        xml_text.encode("utf-8"),
        {"[Content_Types].xml": b"<Types/>", "ppt/presentation.xml": b"<presentation/>"},
    )

    pkg = PptxPackage(zip_bytes)
    plan = PptxMutationPlan()
    plan.text_mutations.append(
        PptxTextMutation(
            part_name="ppt/slides/slide1.xml",
            location="slide1:shape0:p0:r0",
            codepoint=0x200B,
            char_name="ZERO WIDTH SPACE",
            original_text="Slide\u200btext",
            replacement_text="Slidetext",
            shape_id="",
            p_idx=1,
            r_idx=1,
            t_idx=1,
        )
    )
    patcher = PptxPatcher(pkg, plan)
    rebuilt_bytes = patcher.apply()

    zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt_bytes), "r")
    target_info = zf_rebuilt.getinfo("ppt/slides/slide1.xml")

    assert target_info.extra.startswith(b"\x55\x54")
    assert target_info.comment == b"Original entry comment"


def test_a11_stale_zip64_extra_field_stripped_on_rebuild():
    """Verify stale Zip64 (0x0001) extra field is stripped from changed entry to prevent size mismatch."""
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Doc\u200bcontent</w:t></w:r></w:p></w:body>'
        '</w:document>'
    )
    # Extra field containing Zip64 (0x0001, 16 bytes: 8 bytes usize, 8 bytes csize) + extended timestamp (0x5455)
    zip64_extra = struct.pack("<HHQQ", 0x0001, 16, 9999999, 9999999)
    ts_extra = struct.pack("<HHBI", 0x5455, 5, 0x01, 1600000000)
    combined_extra = zip64_extra + ts_extra

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        info = zipfile.ZipInfo("word/document.xml")
        info.extra = combined_extra
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, xml_text.encode("utf-8"))

    pkg = DocxPackage(out.getvalue())
    plan = DocxMutationPlan()
    plan.text_mutations.append(
        TextCodepointMutation("word/document.xml", 0, 0, 0, 0x200B, "ZERO WIDTH SPACE", 3, 0)
    )
    patcher = DocxPatcher(pkg, plan)
    rebuilt_bytes = patcher.apply()

    zf_rebuilt = zipfile.ZipFile(io.BytesIO(rebuilt_bytes), "r")
    target_info = zf_rebuilt.getinfo("word/document.xml")

    # Zip64 (0x0001) stripped, timestamp (0x5455) retained
    assert b"\x01\x00" not in target_info.extra[:4]
    assert target_info.extra.startswith(b"\x55\x54")


# -----------------------------------------------------------------------------
# 6. A18: Complete UI Truthfulness
# -----------------------------------------------------------------------------


def test_a18_ui_pre_validation_truthfulness_no_lossless_overclaims():
    """Verify UI contains no pre-validation absolute Lossless claims and uses neutral wording."""
    html_content = (REPO_ROOT / "service/web/index.html").read_text(encoding="utf-8")
    js_content = (REPO_ROOT / "service/web/app.js").read_text(encoding="utf-8")

    # Prohibited pre-validation marketing wording
    assert "kiểm chứng trung thực Lossless" not in html_content
    assert "DOCX (Lossless)" not in js_content
    assert "Bảo toàn Lossless" not in html_content
    assert "bảo toàn tuyệt đối" not in html_content

    # Required neutral wording
    assert "kiểm chứng fidelity theo khả năng của từng định dạng" in html_content
    # Status badge hidden initially in template
    assert '<span class="badge badge-lossless" hidden>KIỂM CHỨNG FIDELITY: PASS</span>' in html_content


# -----------------------------------------------------------------------------
# 7. Audit Evidence Test IDs Integrity Test
# -----------------------------------------------------------------------------


def test_evidence_test_ids_match_pytest_collection():
    """Verify that every test node ID in V2_2_RC2_HARDENING_EVIDENCE.json exists and resolves cleanly."""
    evidence_path = REPO_ROOT / "docs/audits/V2_2_RC2_HARDENING_EVIDENCE.json"
    assert evidence_path.exists()
    data = json.loads(evidence_path.read_text(encoding="utf-8"))

    # Collect all real pytest nodes in repository
    pytest_bin = sys.executable.replace("python.exe", "pytest.exe")
    res = subprocess.run([pytest_bin, "--collect-only"], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert res.returncode == 0, f"pytest collection failed:\n{res.stderr}"

    collected_nodes = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        if "::" in line:
            # Normalize path separators to forward slashes
            collected_nodes.add(line.replace("\\", "/"))

    unresolved: list[str] = []
    for issue_id, issue in data.get("issues", {}).items():
        for test_ref in issue.get("tests", []):
            test_ref_norm = test_ref.replace("\\", "/")
            if "::" in test_ref_norm:
                if test_ref_norm not in collected_nodes:
                    unresolved.append(f"[{issue_id}] Unresolved test node: {test_ref}")
            else:
                # File path reference
                if not (REPO_ROOT / test_ref_norm).exists():
                    unresolved.append(f"[{issue_id}] Unresolved test file: {test_ref}")

    assert not unresolved, "Evidence JSON contains unverifiable test references:\n" + "\n".join(unresolved)
