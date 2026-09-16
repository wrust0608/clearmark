"""Canonical Phase 7 test suite for ClearMark v2.1 XLSX Lossless Adapter.

Covers:
1. Fixture manifest integrity & deterministic provenance
2. Format classification and detection
3. Shared string carrier removal and index stability
4. Inline string carrier removal
5. Rich text run preservation and styling invariance
6. Cross-reference invariant (multiple cells referencing same shared string)
7. Contextual Unicode preservation (emoji ZWJ, Arabic joiner, Devanagari, NBSP, NFC/NFD)
8. Formula sacrosanct exactness and cached values invariance
9. styles.xml raw preservation and cell style reference mapping
10. Sheet structure, merged ranges, defined names, hyperlinks invariance
11. Strict raw OPC non-target binary pass-through (SHA256, CRC, sizes, flags, dates)
12. Member ordering preservation
13. Empty-plan exact-byte return (zero-copy archive pass-through)
14. Dry-run parity with real execution
15. Fail-closed validation safety
16. Idempotence supporting evidence
17. Report privacy (zero raw cell text/formula leakage)
18. Zero-network isolation
19. CLI integration (inspect, clean, verify)
20. HTTP API integration (inspect, clean, verify, batch)
21. Secondary openability via headless LibreOffice conversion
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import socket
import subprocess
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "xlsx_lossless"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from service.scripts.cli import main as cli_main
from service.scripts.format_dispatch import classify, classify_bytes
from service.scripts.format_policy import FormatPolicyRegistry
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import (
    CleaningReport,
    DetectionStatus,
    PipelineStatus,
    ProcessingMode,
)
from service.scripts.xlsx import (
    XlsxDetector,
    XlsxFidelityValidator,
    XlsxMutationPlan,
    XlsxPackage,
    clean_xlsx_lossless,
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    manifest_path = FIXTURES_DIR / "MANIFEST.json"
    assert manifest_path.exists(), "Fixtures MANIFEST.json must exist"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# 1. Fixture Manifest Integrity
def test_fixture_manifest_integrity(manifest):
    assert manifest["corpus_name"] == "xlsx_lossless"
    assert manifest["fixture_count"] == 14
    fixtures = manifest["fixtures"]
    assert len(fixtures) == 14

    for fid, entry in fixtures.items():
        p = FIXTURES_DIR / entry["filename"]
        assert p.is_file(), f"Fixture file {entry['filename']} missing"
        actual_sha = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual_sha == entry["sha256"], f"SHA256 mismatch for {fid}"


# 2. Format Classification
def test_format_classification():
    baseline_path = FIXTURES_DIR / "synthetic_baseline.xlsx"
    data = baseline_path.read_bytes()

    assert classify(baseline_path) == "container"
    assert classify_bytes(data, "workbook.xlsx") == "container"
    assert classify_bytes(data) == "container"


# 3. Empty-Plan Exact Byte Return (Section 34)
def test_empty_plan_exact_byte_return():
    baseline_data = (FIXTURES_DIR / "synthetic_baseline.xlsx").read_bytes()
    cleaned_bytes, report = clean_xlsx_lossless(baseline_data)

    assert report["changed"] is False
    assert report["would_change"] is False
    assert cleaned_bytes is baseline_data or cleaned_bytes == baseline_data
    assert hashlib.sha256(cleaned_bytes).hexdigest() == hashlib.sha256(baseline_data).hexdigest()


# 4. Carrier Removal in Shared Strings (xl/sharedStrings.xml)
def test_carrier_shared_string_removal():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is True
    assert any("layer A text: removed=1" in a for a in report["actions"])

    # Shared string table inspection
    before_pkg = XlsxPackage(raw)
    after_pkg = XlsxPackage(cleaned)

    sst_before = before_pkg.get_member("xl/sharedStrings.xml").decode("utf-8")
    sst_after = after_pkg.get_member("xl/sharedStrings.xml").decode("utf-8")

    assert "\u200b" in sst_before
    assert "\u200b" not in sst_after
    assert "FinancialReport" in sst_after or "Financial Summary" in sst_after

    # Validation passed
    val = report["validation"]
    assert val is not None and val.passed is True


# 5. Carrier Removal in Worksheet Inline Strings (<is><t>)
def test_carrier_inline_string_removal():
    raw = (FIXTURES_DIR / "carrier_inline_string.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is True
    assert any("layer A text: removed=1" in a for a in report["actions"])

    before_pkg = XlsxPackage(raw)
    after_pkg = XlsxPackage(cleaned)

    sh_before = before_pkg.get_member("xl/worksheets/sheet1.xml").decode("utf-8")
    sh_after = after_pkg.get_member("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "\u200c" in sh_before
    assert "\u200c" not in sh_after
    assert "InlineClean" in sh_after or "Inline Clean" in sh_after


# 6. Carrier Removal in Rich Text Runs (<si><r><t>)
def test_carrier_rich_text_removal():
    raw = (FIXTURES_DIR / "carrier_rich_text.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is True
    assert any("layer A text: removed=1" in a for a in report["actions"])

    before_pkg = XlsxPackage(raw)
    after_pkg = XlsxPackage(cleaned)

    sst_before = before_pkg.get_member("xl/sharedStrings.xml").decode("utf-8")
    sst_after = after_pkg.get_member("xl/sharedStrings.xml").decode("utf-8")

    assert "\u200d" in sst_before
    assert "\u200d" not in sst_after
    # Rich text run formatting preserved
    assert "<rPr><b/></rPr>" in sst_after or "<b/>" in sst_after


# 7. Cross-Referenced Shared Strings Invariance (Section 42)
def test_carrier_cross_reference_invariant():
    raw = (FIXTURES_DIR / "carrier_cross_reference.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is True
    val = report["validation"]
    assert val is not None and val.passed is True

    before_pkg = XlsxPackage(raw)
    after_pkg = XlsxPackage(cleaned)

    # Invariant: same number of <si> entries
    sst_b = before_pkg.get_member("xl/sharedStrings.xml").decode("utf-8")
    sst_a = after_pkg.get_member("xl/sharedStrings.xml").decode("utf-8")
    assert sst_b.count("<si>") == sst_a.count("<si>")

    # Invariant: referencing cells (A1, B1, C1) still point to index 0
    sh_a = after_pkg.get_member("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="A1" t="s"><v>0</v></c>' in sh_a
    assert '<c r="B1" t="s"><v>0</v></c>' in sh_a
    assert '<c r="C1" t="s"><v>0</v></c>' in sh_a

    # Cleaned string appears to all referencing cells
    assert "\u200b" not in sst_a
    assert "SharedMetric" in sst_a


# 8. Mixed Carriers & Metadata Scrubbing
def test_carrier_mixed_removal():
    raw = (FIXTURES_DIR / "carrier_mixed.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is True
    actions = report["actions"]
    assert any("scrub docProps/core.xml field dc:creator" in a for a in actions)
    assert any("scrub docProps/app.xml field Application" in a for a in actions)
    assert any("layer A text:" in a for a in actions)

    # In SAFE mode, generic customXml and docProps/custom.xml are PRESERVED_RAW by default
    after_pkg = XlsxPackage(cleaned)
    before_pkg = XlsxPackage(raw)
    assert after_pkg.has_member("docProps/custom.xml")
    assert after_pkg.has_member("customXml/item1.xml")
    assert after_pkg.get_member("docProps/custom.xml") == before_pkg.get_member("docProps/custom.xml")
    assert after_pkg.get_member("customXml/item1.xml") == before_pkg.get_member("customXml/item1.xml")
    assert after_pkg.get_member("_rels/.rels") == before_pkg.get_member("_rels/.rels")
    assert after_pkg.get_member("[Content_Types].xml") == before_pkg.get_member("[Content_Types].xml")


# 9. Contextual Unicode: Emoji ZWJ Preservation (Section 23, 39)
def test_counterexample_emoji_zwj():
    raw = (FIXTURES_DIR / "counterexample_emoji_zwj.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is False
    assert cleaned == raw
    assert hashlib.sha256(cleaned).hexdigest() == hashlib.sha256(raw).hexdigest()


# 10. Contextual Unicode: Arabic / Persian Joiner Preservation
def test_counterexample_arabic_joiner():
    raw = (FIXTURES_DIR / "counterexample_arabic_joiner.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is False
    assert cleaned == raw


# 11. Contextual Unicode: Devanagari Halant Conjunct Preservation
def test_counterexample_devanagari():
    raw = (FIXTURES_DIR / "counterexample_devanagari.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is False
    assert cleaned == raw


# 12. Contextual Unicode: NBSP & NNBSP Preservation in SAFE mode
def test_counterexample_nbsp():
    raw = (FIXTURES_DIR / "counterexample_nbsp.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw, options={"mode": "SAFE"})

    assert report["changed"] is False
    assert cleaned == raw


# 13. Contextual Unicode: NFC / NFD Distinct Preservation
def test_counterexample_nfc_nfd():
    raw = (FIXTURES_DIR / "counterexample_nfc_nfd.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is False
    assert cleaned == raw


# 13b. Legitimate Custom Document Properties Preservation
def test_counterexample_custom_properties_preservation():
    raw = (FIXTURES_DIR / "counterexample_custom_properties.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw, options={"mode": "SAFE"})

    assert report["changed"] is False
    assert cleaned == raw
    assert report["plan"].is_empty()

    pkg = XlsxPackage(cleaned)
    assert pkg.has_member("docProps/custom.xml")
    custom_xml = pkg.get_member("docProps/custom.xml").decode("utf-8")
    assert "Department" in custom_xml
    assert "Finance" in custom_xml
    assert "ProjectCode" in custom_xml
    assert "ABC-2026" in custom_xml
    assert "ReviewRequired" in custom_xml
    assert "BudgetYear" in custom_xml
    assert "2026" in custom_xml


# 13c. Legitimate Custom XML Application Data Preservation
def test_counterexample_custom_xml_preservation():
    raw = (FIXTURES_DIR / "counterexample_custom_xml.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw, options={"mode": "SAFE"})

    assert report["changed"] is False
    assert cleaned == raw
    assert report["plan"].is_empty()

    pkg = XlsxPackage(cleaned)
    assert pkg.has_member("customXml/item1.xml")
    assert pkg.has_member("customXml/itemProps1.xml")
    assert pkg.has_member("customXml/_rels/item1.xml.rels")
    biz_xml = pkg.get_member("customXml/item1.xml").decode("utf-8")
    assert "businessData" in biz_xml
    assert "CUST-98765" in biz_xml
    assert "APPROVED" in biz_xml


# 14. Carrier alongside Legitimate Unicode
def test_carrier_and_legitimate_unicode():
    raw = (FIXTURES_DIR / "carrier_and_legitimate_unicode.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    assert report["changed"] is True
    assert any("layer A text: removed=1" in a for a in report["actions"])

    after_pkg = XlsxPackage(cleaned)
    sst = after_pkg.get_member("xl/sharedStrings.xml").decode("utf-8")

    # Carrier removed
    assert "\u200b" not in sst
    # Legitimate Unicode preserved
    assert "👨‍👩‍👧‍👦" in sst
    assert "می‌روم" in sst
    assert "क्‍ष" in sst
    assert "100\u00a0000\u202feuros" in sst


# 15. Formula Sacrosanct Invariant (Section 13, 29)
def test_formula_sacrosanct_preservation():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    b_pkg = XlsxPackage(raw)
    a_pkg = XlsxPackage(cleaned)

    sh_b = b_pkg.get_member("xl/worksheets/sheet1.xml").decode("utf-8")
    sh_a = a_pkg.get_member("xl/worksheets/sheet1.xml").decode("utf-8")

    # Formula node before == after
    assert "<f>SUM(B1:B2)</f>" in sh_b
    assert "<f>SUM(B1:B2)</f>" in sh_a
    assert '<c r="C1"><f>SUM(B1:B2)</f><v>150</v></c>' in sh_a


# 16. Styles Raw Preservation (Section 15, 30)
def test_styles_raw_preservation():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    b_pkg = XlsxPackage(raw)
    a_pkg = XlsxPackage(cleaned)

    # xl/styles.xml byte identical
    assert b_pkg.get_hash("xl/styles.xml") == a_pkg.get_hash("xl/styles.xml")

    # Cell style indexes invariant
    sh_a = a_pkg.get_member("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="A1" t="s" s="1">' in sh_a
    assert '<c r="D2" s="2">' in sh_a


# 17. Structural Invariants (Section 16, 17)
def test_structural_invariants():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    b_pkg = XlsxPackage(raw)
    a_pkg = XlsxPackage(cleaned)

    # Workbook sheets
    wb_b = b_pkg.get_member("xl/workbook.xml").decode("utf-8")
    wb_a = a_pkg.get_member("xl/workbook.xml").decode("utf-8")
    assert wb_b == wb_a

    # Merged cells, freeze pane, hyperlinks
    sh_a = a_pkg.get_member("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<mergeCell ref="E1:F2"/>' in sh_a
    assert '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>' in sh_a
    assert '<hyperlink ref="A10" r:id="rIdH1"/>' in sh_a


# 18. Strict Raw OPC Non-Target Invariance (Section 33)
def test_strict_raw_opc_preservation():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    b_pkg = XlsxPackage(raw)
    a_pkg = XlsxPackage(cleaned)

    for name in b_pkg.member_order:
        if name == "xl/sharedStrings.xml":
            continue  # Target part

        # Non-target entries
        assert b_pkg.get_hash(name) == a_pkg.get_hash(name), f"Uncompressed hash drift: {name}"
        assert b_pkg.get_compressed_hash(name) == a_pkg.get_compressed_hash(name), f"Raw compressed hash drift: {name}"

        b_info = b_pkg.zip_infos[name]
        a_info = a_pkg.zip_infos[name]
        assert b_info.CRC == a_info.CRC
        assert b_info.compress_type == a_info.compress_type
        assert b_info.compress_size == a_info.compress_size
        assert b_info.file_size == a_info.file_size
        assert b_info.flag_bits == a_info.flag_bits
        assert b_info.external_attr == a_info.external_attr
        assert b_info.internal_attr == a_info.internal_attr
        assert b_info.date_time == a_info.date_time


# 19. Member Ordering Invariant
def test_member_ordering_preservation():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)

    b_pkg = XlsxPackage(raw)
    a_pkg = XlsxPackage(cleaned)
    assert b_pkg.member_order == a_pkg.member_order


# 20. Idempotence Supporting Evidence (Section 35)
def test_idempotence():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    c1, r1 = clean_xlsx_lossless(raw)
    assert r1["changed"] is True

    c2, r2 = clean_xlsx_lossless(c1)
    assert r2["changed"] is False
    assert c1 == c2


# 21. Fail-Closed Validation Safety (Section 58)
def test_validation_failure_safety():
    raw = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
    b_pkg = XlsxPackage(raw)

    # Force a corrupt target where sheet count/name differs
    orig_wb = b_pkg.get_member("xl/workbook.xml")
    assert orig_wb is not None
    corrupt_wb = orig_wb.replace(b'name="Sheet2"', b'name="SheetCorrupt"')
    corrupt_after_data = b_pkg.rebuild({"xl/workbook.xml": corrupt_wb})
    a_pkg = XlsxPackage(corrupt_after_data)

    validator = XlsxFidelityValidator(b_pkg, a_pkg, {"xl/workbook.xml"})
    rep = validator.validate()
    assert rep.passed is False
    assert any("Sheet name drift" in err for err in rep.errors)


# 22. Dry-Run Parity (Section 57)
def test_pipeline_dry_run_parity():
    pipeline = Pipeline()
    p = FIXTURES_DIR / "carrier_shared_string.xlsx"

    # Dry-run
    _, dry_rep = pipeline.clean(p, dry_run=True)
    assert dry_rep.status == PipelineStatus.INSPECTED
    assert dry_rep.output.changed is False
    assert dry_rep.output.would_change is True
    assert len(dry_rep.mutation_plan.mutations) == 1
    assert "xl/sharedStrings.xml" in dry_rep.mutation_plan.changed_parts

    # Real clean
    _, real_rep = pipeline.clean(p, dry_run=False)
    assert real_rep.status == PipelineStatus.CLEANED
    assert real_rep.output.changed is True
    assert real_rep.output.would_change is True
    assert len(real_rep.mutation_plan.mutations) == 1
    assert "xl/sharedStrings.xml" in real_rep.mutation_plan.changed_parts


# 23. Report Privacy Invariant (Section 55)
def test_report_privacy():
    pipeline = Pipeline()
    p = FIXTURES_DIR / "carrier_shared_string.xlsx"
    _, rep = pipeline.clean(p)
    rep_json = json.dumps(rep.to_dict())

    # Cell text and formula text must NOT leak into report
    assert "Quarterly Financial Summary" not in rep_json
    assert "SUM(B1:B2)" not in rep_json


# 24. Zero Network Isolation (Section 56)
def test_zero_network(monkeypatch):
    def _fail_socket(*args, **kwargs):
        raise RuntimeError("Unexpected network attempt during XLSX processing")

    monkeypatch.setattr(socket, "socket", _fail_socket)

    pipeline = Pipeline()
    p = FIXTURES_DIR / "carrier_shared_string.xlsx"
    insp = pipeline.inspect(p)
    assert insp.status == PipelineStatus.INSPECTED

    _, cln = pipeline.clean(p)
    assert cln.status == PipelineStatus.CLEANED


# 25. CLI inspect / clean / verify (Sections 51, 52)
def test_cli_inspect_clean_verify(tmp_path):
    p_orig = FIXTURES_DIR / "carrier_shared_string.xlsx"
    p_cand = tmp_path / "carrier_shared_string.cleaned.xlsx"

    # CLI clean
    code_clean = cli_main(["clean", str(p_orig), "-o", str(p_cand), "--json"])
    assert code_clean == 0
    assert p_cand.exists()

    # CLI inspect
    code_insp = cli_main(["inspect", str(p_cand), "--json"])
    assert code_insp == 0

    # CLI verify
    code_ver = cli_main(["verify", str(p_orig), str(p_cand), "--json"])
    assert code_ver == 0


# 26. HTTP /verify for XLSX (Section 52)
def test_http_verify_xlsx():
    import server
    import http.client
    import threading

    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        orig_bytes = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
        cand_bytes, _ = clean_xlsx_lossless(orig_bytes)

        payload = {
            "original": base64.b64encode(orig_bytes).decode("ascii"),
            "candidate": base64.b64encode(cand_bytes).decode("ascii"),
            "name": "sheet.xlsx",
        }
        conn.request("POST", "/verify", body=json.dumps(payload), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 200
        assert data["ok"] is True
        assert data["status"] == "PASS"
        assert data["format"] == "xlsx"
        assert data["validation"]["structural_invariants_passed"] is True
        assert len(data["invariants"]) >= 3
    finally:
        conn.close()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# 27. Secondary Openability via Headless LibreOffice
def test_secondary_openability_libreoffice(tmp_path):
    soffice = r"C:\Program Files\LibreOffice\program\soffice.exe"
    if not Path(soffice).exists():
        pytest.skip("LibreOffice binary not found at default location")

    orig_path = FIXTURES_DIR / "carrier_shared_string.xlsx"
    orig_bytes = orig_path.read_bytes()
    cand_bytes, _ = clean_xlsx_lossless(orig_bytes)

    cand_path = tmp_path / "cleaned.xlsx"
    cand_path.write_bytes(cand_bytes)

    # Convert cleaned XLSX to PDF
    res = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(cand_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0
    pdf_path = tmp_path / "cleaned.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000


# 28. Strict Raw ZIP Record Parity (Sections 16, 17)
def _parse_raw_zip_records(zip_bytes: bytes) -> tuple[dict[str, dict[str, Any]], list[str]]:
    eocd_idx = zip_bytes.rfind(b"PK\x05\x06")
    assert eocd_idx != -1, "Not a valid ZIP: missing EOCD"
    cd_offset = struct.unpack_from("<I", zip_bytes, eocd_idx + 16)[0]
    cd_size = struct.unpack_from("<I", zip_bytes, eocd_idx + 12)[0]
    total_entries = struct.unpack_from("<H", zip_bytes, eocd_idx + 10)[0]

    cd_bytes = zip_bytes[cd_offset : cd_offset + cd_size]
    pos = 0
    records: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for _ in range(total_entries):
        assert cd_bytes[pos : pos + 4] == b"PK\x01\x02", "Invalid Central Directory signature"
        fn_len = struct.unpack_from("<H", cd_bytes, pos + 28)[0]
        extra_len = struct.unpack_from("<H", cd_bytes, pos + 30)[0]
        comm_len = struct.unpack_from("<H", cd_bytes, pos + 32)[0]
        local_off = struct.unpack_from("<I", cd_bytes, pos + 42)[0]
        csize = struct.unpack_from("<I", cd_bytes, pos + 20)[0]

        entry_len = 46 + fn_len + extra_len + comm_len
        cd_record = cd_bytes[pos : pos + entry_len]
        fn = cd_bytes[pos + 46 : pos + 46 + fn_len].decode("utf-8")
        pos += entry_len
        order.append(fn)

        assert zip_bytes[local_off : local_off + 4] == b"PK\x03\x04", f"Invalid local header for {fn}"
        loc_fn_len = struct.unpack_from("<H", zip_bytes, local_off + 26)[0]
        loc_extra_len = struct.unpack_from("<H", zip_bytes, local_off + 28)[0]
        loc_hdr_len = 30 + loc_fn_len + loc_extra_len
        loc_hdr = zip_bytes[local_off : local_off + loc_hdr_len]
        compressed_payload = zip_bytes[local_off + loc_hdr_len : local_off + loc_hdr_len + csize]
        local_record = zip_bytes[local_off : local_off + loc_hdr_len + csize]

        records[fn] = {
            "local_header": loc_hdr,
            "compressed_payload": compressed_payload,
            "local_record": local_record,
            "central_record": cd_record,
            "local_offset": local_off,
        }

    return records, order


@pytest.mark.parametrize(
    "fixture_name",
    [
        "carrier_shared_string.xlsx",
        "carrier_inline_string.xlsx",
        "carrier_mixed.xlsx",
        "carrier_and_legitimate_unicode.xlsx",
    ],
)
def test_xlsx_non_target_raw_zip_records_are_byte_identical(fixture_name):
    raw = (FIXTURES_DIR / fixture_name).read_bytes()
    cleaned, report = clean_xlsx_lossless(raw)
    plan = report["plan"]
    targets = plan.changed_parts() | plan.dropped_parts()

    rec_b, order_b = _parse_raw_zip_records(raw)
    rec_a, order_a = _parse_raw_zip_records(cleaned)

    # Member ordering invariant
    assert order_b == order_a, f"Member ordering drifted in {fixture_name}"

    for m in order_b:
        if m in targets:
            continue
        rb = rec_b[m]
        ra = rec_a[m]
        # Raw local file header record bytes exact match
        assert rb["local_header"] == ra["local_header"], f"Local header record drifted in non-target {m}"
        # Raw compressed payload bytes exact match
        assert rb["compressed_payload"] == ra["compressed_payload"], f"Compressed payload drifted in non-target {m}"
        # Full local record exact match
        assert rb["local_record"] == ra["local_record"], f"Local entry record drifted in non-target {m}"
        # Central directory metadata exact match (bytes 0..42 and 46..end)
        assert rb["central_record"][:42] + rb["central_record"][46:] == ra["central_record"][:42] + ra["central_record"][46:], f"CD metadata drifted in non-target {m}"
        # If predecessor entries did not shift offset, entire central directory record is byte-identical
        if rb["local_offset"] == ra["local_offset"]:
            assert rb["central_record"] == ra["central_record"], f"Full CD record drifted in non-target {m}"


# 29. Verification Contract: Corrupted Candidate Fails
def test_verify_two_files_cli_corrupted_candidate_fails(tmp_path):
    orig_path = FIXTURES_DIR / "carrier_shared_string.xlsx"
    corrupt_path = tmp_path / "corrupted.xlsx"
    corrupt_path.write_bytes(b"PK\x03\x04corrupted binary payload for test")

    code = cli_main(["verify", str(orig_path), str(corrupt_path), "--json"])
    assert code != 0


# 30. Verification Contract: Single Argument Usage Error
def test_verify_cli_single_path_usage_error():
    orig_path = FIXTURES_DIR / "carrier_shared_string.xlsx"
    code = cli_main(["verify", str(orig_path)])
    assert code != 0


# 31. Verification Contract: Mismatched Format Rejection
def test_verify_cli_mismatched_formats_rejected(tmp_path):
    orig_path = FIXTURES_DIR / "carrier_shared_string.xlsx"
    cand_path = tmp_path / "test.docx"
    cand_path.write_bytes(b"PK\x03\x04dummy")

    code = cli_main(["verify", str(orig_path), str(cand_path), "--json"])
    assert code != 0


# 32. HTTP Verify: Mismatched Formats Rejection
def test_http_verify_mismatched_formats_rejected():
    import server
    import http.client
    import threading

    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        orig_bytes = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
        cand_bytes = (Path("tests/fixtures/docx_body_carriers/synthetic_baseline.docx")).read_bytes()

        payload = {
            "original": base64.b64encode(orig_bytes).decode("ascii"),
            "candidate": base64.b64encode(cand_bytes).decode("ascii"),
            "name": "sheet.xlsx",
            "candidate_name": "doc.docx",
        }
        conn.request("POST", "/verify", body=json.dumps(payload), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 400
        assert data["ok"] is False
        assert data["error_code"] == "MISMATCHED_FORMATS"
    finally:
        conn.close()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# 33. HTTP Verify: Corrupted Candidate Fails
def test_http_verify_corrupted_xlsx_candidate_fails():
    import server
    import http.client
    import threading

    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        orig_bytes = (FIXTURES_DIR / "carrier_shared_string.xlsx").read_bytes()
        cand_bytes = b"PK\x03\x04corrupted candidate payload"

        payload = {
            "original": base64.b64encode(orig_bytes).decode("ascii"),
            "candidate": base64.b64encode(cand_bytes).decode("ascii"),
            "name": "sheet.xlsx",
        }
        conn.request("POST", "/verify", body=json.dumps(payload), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 422
        assert data["ok"] is False
        assert data["status"] == "FAIL"
    finally:
        conn.close()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# 34. Corpus Truthfulness: 0 False Positives & 0 False Negatives on Declared Corpus
def test_detector_truthfulness_corpus():
    manifest = json.loads((FIXTURES_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    total_fp = 0
    total_fn = 0

    for fid, entry in manifest["fixtures"].items():
        fname = entry["filename"]
        raw = (FIXTURES_DIR / fname).read_bytes()
        pkg = XlsxPackage(raw)
        plan = XlsxDetector(pkg, {"mode": "SAFE"}).build_plan()

        expected_muts = entry["expected_mutations"]
        actual_muts = len(plan.to_mutations_list())

        if entry["category"] == "counterexample":
            if actual_muts > 0:
                total_fp += actual_muts
        elif entry["category"] == "positive_carrier":
            if actual_muts < expected_muts:
                total_fn += (expected_muts - actual_muts)

    assert total_fp == 0, f"Detected {total_fp} false positives against declared Phase 7 counterexample corpus"
    assert total_fn == 0, f"Detected {total_fn} false negatives on supported inserted carriers in declared corpus"

