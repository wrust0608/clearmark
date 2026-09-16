"""Canonical Phase 8 test suite for ClearMark v2.1 PPTX Lossless Adapter.

Covers:
1. Fixture manifest integrity & deterministic provenance
2. Format classification and detection
3. Renamed non-PPTX package rejection / fail-closed
4. Primary slide text carrier removal
5. Multi-run preservation and styling invariance
6. Table text carrier removal and table structure preservation
7. Contextual Unicode preservation (emoji ZWJ, Arabic joiner, Devanagari, NBSP, NFC/NFD)
8. Slide master, layout, theme, notes, field, and group shape boundary preservation (counterexamples)
9. Custom document properties and customXml preservation (counterexamples)
10. Strict raw OPC non-target binary pass-through (SHA256, CRC, sizes, flags, dates)
11. Member ordering preservation
12. Empty-plan exact-byte return (zero-copy archive pass-through)
13. Dry-run parity with real execution
14. Fail-closed validation safety on deliberate invariant corruption (negative witnesses)
15. Signed and macro presentation fail-closed safety
16. Idempotence supporting evidence
17. Report privacy (zero raw slide text/notes leakage)
18. Zero-network isolation
19. CLI integration (inspect, clean, verify)
20. HTTP API integration (inspect, clean, verify, batch)
21. Secondary openability via headless LibreOffice conversion
22. Cross-format verification matrix
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "pptx_lossless"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from service.scripts.cli import main as cli_main
from service.scripts.container_meta import detect_container_format
from service.scripts.format_dispatch import classify, classify_bytes
from service.scripts.format_policy import FormatPolicyRegistry
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import (
    CleaningReport,
    DetectionStatus,
    ErrorCode,
    PipelineStatus,
    ProcessingMode,
)
from service.scripts.pptx import (
    PptxDetector,
    PptxFidelityValidator,
    PptxMutationPlan,
    PptxPackage,
    clean_pptx_lossless,
)
from service.scripts.pptx.exceptions import PptxError, PptxValidationError


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    manifest_path = FIXTURES_DIR / "MANIFEST.json"
    assert manifest_path.exists(), "Fixtures MANIFEST.json must exist"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# 1. Fixture Manifest Integrity (Sections 58, 72, 73)
def test_fixture_manifest_integrity(manifest):
    assert len(manifest) == 17, f"Expected 17 fixtures, found {len(manifest)}"

    for fid, entry in manifest.items():
        p = FIXTURES_DIR / entry["filename"]
        assert p.is_file(), f"Fixture file {entry['filename']} missing"
        actual_sha = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual_sha == entry["sha256"], f"SHA256 mismatch for {fid}"


# 2. Deterministic Fixture Generation (Section 58)
def test_deterministic_fixture_generation(manifest):
    from tests.fixtures.pptx_lossless.build_fixtures import build_all_fixtures

    with tempfile.TemporaryDirectory() as td:
        build_all_fixtures(Path(td))
        for fid, entry in manifest.items():
            generated_file = Path(td) / entry["filename"]
            assert generated_file.exists()
            gen_sha = hashlib.sha256(generated_file.read_bytes()).hexdigest()
            assert gen_sha == entry["sha256"], f"Regenerated fixture {fid} SHA mismatch"


# 3. Format Classification and Sniffing (Section 80)
def test_format_classification():
    baseline_path = FIXTURES_DIR / "synthetic_clean_baseline.pptx"
    data = baseline_path.read_bytes()

    assert classify(baseline_path) == "container"
    assert classify_bytes(data, "presentation.pptx") == "container"
    assert classify_bytes(data) == "container"
    assert detect_container_format(baseline_path, data) == "pptx"


# 4. Renamed Non-PPTX Rejection / Fail-Closed (Section 80)
def test_renamed_non_pptx_rejection():
    # Plain ZIP without presentation parts
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.txt", "hello")
    fake_data = buf.getvalue()

    # detect_container_format should not classify as pptx
    assert detect_container_format(Path("fake.pptx"), fake_data) != "pptx"

    # clean_pptx_lossless should fail closed
    with pytest.raises(PptxError):
        clean_pptx_lossless(fake_data)


# 5. Slide Text Carrier Removal (Sections 6, 9, 10, 11, 12, 13)
def test_carrier_slide_text_removal():
    orig_path = FIXTURES_DIR / "carrier_slide_text.pptx"
    orig_bytes = orig_path.read_bytes()

    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)

    assert cleaned_bytes != orig_bytes
    assert report["changed"] is True
    plan: PptxMutationPlan = report["plan"]
    assert len(plan.text_mutations) == 1
    mut = plan.text_mutations[0]
    assert mut.part_name == "ppt/slides/slide1.xml"
    assert mut.target_codepoint == "U+200B"

    # Slide 1 XML must not contain U+200B
    pkg_cleaned = PptxPackage(cleaned_bytes)
    slide1_cleaned = pkg_cleaned.get_member("ppt/slides/slide1.xml").decode("utf-8")
    assert "\u200b" not in slide1_cleaned
    assert "Presentation Title" in slide1_cleaned

    # Non-target slide 2 XML must be identical
    pkg_orig = PptxPackage(orig_bytes)
    assert pkg_cleaned.get_member("ppt/slides/slide2.xml") == pkg_orig.get_member("ppt/slides/slide2.xml")


# 6. Multi-Run Preservation (Section 9)
def test_carrier_multi_run_removal():
    orig_path = FIXTURES_DIR / "carrier_multi_run.pptx"
    orig_bytes = orig_path.read_bytes()

    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)
    assert report["changed"] is True
    plan: PptxMutationPlan = report["plan"]
    assert len(plan.text_mutations) == 2

    pkg = PptxPackage(cleaned_bytes)
    slide1 = pkg.get_member("ppt/slides/slide1.xml").decode("utf-8")
    assert "\u200b" not in slide1
    assert "\u200c" not in slide1

    # Run order and content invariant except carrier
    assert "Presentation Title" in slide1
    assert "Subtitle Here" in slide1


# 7. Table Text Carrier Removal (Section 15)
def test_carrier_table_text_removal():
    orig_path = FIXTURES_DIR / "carrier_table_text.pptx"
    orig_bytes = orig_path.read_bytes()

    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)
    assert report["changed"] is True
    plan: PptxMutationPlan = report["plan"]
    assert len(plan.text_mutations) == 1
    assert plan.text_mutations[0].part_name == "ppt/slides/slide2.xml"

    pkg = PptxPackage(cleaned_bytes)
    slide2 = pkg.get_member("ppt/slides/slide2.xml").decode("utf-8")
    assert "\u200b" not in slide2
    assert "Header A" in slide2


# 8. Carrier and Legitimate Contextual Unicode (Section 41)
def test_carrier_and_legitimate_unicode_preservation():
    orig_path = FIXTURES_DIR / "carrier_and_legitimate_unicode.pptx"
    orig_bytes = orig_path.read_bytes()

    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)
    assert report["changed"] is True
    plan: PptxMutationPlan = report["plan"]
    assert len(plan.text_mutations) == 1

    pkg = PptxPackage(cleaned_bytes)
    slide1 = pkg.get_member("ppt/slides/slide1.xml").decode("utf-8")
    assert "\u200b" not in slide1
    assert "Hello" in slide1
    assert "World" in slide1
    # Family emoji ZWJ sequence must be preserved intact
    assert "\U0001f468\u200d\U0001f469\u200d\U0001f466" in slide1


# 9. Mixed Carrier Fixture (Section 61)
def test_carrier_mixed_removal():
    orig_path = FIXTURES_DIR / "carrier_mixed.pptx"
    orig_bytes = orig_path.read_bytes()

    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)
    assert report["changed"] is True
    plan: PptxMutationPlan = report["plan"]

    # Planned parts: slide1, slide2, docProps/core.xml, docProps/app.xml
    changed_parts = plan.changed_parts()
    assert "ppt/slides/slide1.xml" in changed_parts
    assert "ppt/slides/slide2.xml" in changed_parts
    assert "docProps/core.xml" in changed_parts
    assert "docProps/app.xml" in changed_parts

    # Media, masters, layouts, themes MUST be untouched
    pkg_b = PptxPackage(orig_bytes)
    pkg_a = PptxPackage(cleaned_bytes)

    for m in pkg_b.member_order:
        if m in ("ppt/slides/slide1.xml", "ppt/slides/slide2.xml", "docProps/core.xml", "docProps/app.xml"):
            continue
        assert pkg_b.get_member(m) == pkg_a.get_member(m), f"Non-target part {m} drifted"


# 10. Counterexamples Zero Modifications (Sections 18, 19, 20, 21, 32, 62, 63, 64, 65, 71)
@pytest.mark.parametrize(
    "fixture_name",
    [
        "counterexample_emoji_zwj.pptx",
        "counterexample_arabic_joiner.pptx",
        "counterexample_devanagari.pptx",
        "counterexample_nbsp.pptx",
        "counterexample_nfc_nfd.pptx",
        "counterexample_custom_properties.pptx",
        "counterexample_custom_xml.pptx",
        "counterexample_field.pptx",
        "counterexample_notes.pptx",
        "counterexample_master.pptx",
        "counterexample_group_shape.pptx",
    ],
)
def test_counterexamples_zero_modifications(fixture_name):
    orig_bytes = (FIXTURES_DIR / fixture_name).read_bytes()
    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)

    assert report["changed"] is False
    assert report["plan"].total_mutations() == 0
    assert cleaned_bytes == orig_bytes
    assert hashlib.sha256(cleaned_bytes).hexdigest() == hashlib.sha256(orig_bytes).hexdigest()


# 11. Structural Invariants Preservation (Sections 10, 11, 12, 13, 16, 17, 30)
def test_structural_invariants_preserved():
    orig_path = FIXTURES_DIR / "carrier_slide_text.pptx"
    orig_bytes = orig_path.read_bytes()

    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)
    val_report = report["validation"]

    assert val_report.passed is True
    assert len(val_report.errors) == 0

    # Explicit check on slide IDs and presentation order
    pkg_b = PptxPackage(orig_bytes)
    pkg_a = PptxPackage(cleaned_bytes)

    pres_b = pkg_b.get_member("ppt/presentation.xml")
    pres_a = pkg_a.get_member("ppt/presentation.xml")
    assert pres_b == pres_a, "ppt/presentation.xml must remain byte-identical"


# 12. Media Raw Preservation (Section 26, 50)
def test_media_raw_preservation():
    orig_path = FIXTURES_DIR / "carrier_mixed.pptx"
    orig_bytes = orig_path.read_bytes()

    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)
    pkg_b = PptxPackage(orig_bytes)
    pkg_a = PptxPackage(cleaned_bytes)

    media_members = [m for m in pkg_b.member_order if m.startswith("ppt/media/")]
    assert len(media_members) > 0, "carrier_mixed.pptx should contain media"

    for m in media_members:
        assert pkg_b.get_member(m) == pkg_a.get_member(m), f"Media {m} uncompressed drifted"
        assert pkg_b.get_compressed_payload(m) == pkg_a.get_compressed_payload(m), f"Media {m} raw compressed drifted"
        assert pkg_b.get_raw_local_record(m) == pkg_a.get_raw_local_record(m), f"Media {m} raw local record drifted"


# 13. Strict Raw ZIP Record Parity (Sections 55, 56)
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
        "carrier_slide_text.pptx",
        "carrier_multi_run.pptx",
        "carrier_table_text.pptx",
        "carrier_mixed.pptx",
    ],
)
def test_pptx_non_target_raw_zip_records_are_byte_identical(fixture_name):
    raw = (FIXTURES_DIR / fixture_name).read_bytes()
    cleaned, report = clean_pptx_lossless(raw)
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
        assert (
            rb["central_record"][:42] + rb["central_record"][46:]
            == ra["central_record"][:42] + ra["central_record"][46:]
        ), f"CD metadata drifted in non-target {m}"
        # If predecessor entries did not shift offset, entire central directory record is byte-identical
        if rb["local_offset"] == ra["local_offset"]:
            assert rb["central_record"] == ra["central_record"], f"Full CD record drifted in non-target {m}"


# 14. Empty Plan Exact Identity (Sections 39, 75)
def test_empty_plan_exact_identity():
    orig_bytes = (FIXTURES_DIR / "synthetic_clean_baseline.pptx").read_bytes()
    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)

    assert cleaned_bytes is orig_bytes
    assert report["changed"] is False
    assert report["plan"].total_mutations() == 0
    assert hashlib.sha256(cleaned_bytes).hexdigest() == hashlib.sha256(orig_bytes).hexdigest()


# 15. Dry Run Parity (Section 77)
def test_dry_run_parity():
    orig_path = FIXTURES_DIR / "carrier_slide_text.pptx"

    pipeline = Pipeline()
    _, dry_rep = pipeline.clean(orig_path, dry_run=True)
    assert dry_rep.status == PipelineStatus.INSPECTED
    assert dry_rep.output.would_change is True
    assert dry_rep.output.changed is False

    _, real_rep = pipeline.clean(orig_path, dry_run=False)
    assert real_rep.status == PipelineStatus.CLEANED
    assert real_rep.output.would_change is True
    assert real_rep.output.changed is True

    # Parity of mutation plans
    assert len(dry_rep.mutation_plan.mutations) == len(real_rep.mutation_plan.mutations)
    assert dry_rep.mutation_plan.changed_parts == real_rep.mutation_plan.changed_parts


# 16. Supporting Idempotence (Section 76)
def test_idempotence_supporting_evidence():
    orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()
    cleaned_first, rep1 = clean_pptx_lossless(orig_bytes)
    assert rep1["changed"] is True

    cleaned_second, rep2 = clean_pptx_lossless(cleaned_first)
    assert rep2["changed"] is False
    assert rep2["plan"].total_mutations() == 0
    assert cleaned_second == cleaned_first
    assert hashlib.sha256(cleaned_second).hexdigest() == hashlib.sha256(cleaned_first).hexdigest()


# 17. Report Privacy (Section 87)
def test_report_privacy():
    pipeline = Pipeline()
    p = FIXTURES_DIR / "carrier_slide_text.pptx"
    _, rep = pipeline.clean(p)
    serialized = json.dumps(rep.to_dict())

    # Ensure slide text payload is not dumped in full
    assert "Overview of the project architecture" not in serialized
    assert "Slide 1" not in serialized


# 18. Zero Network Isolation (Section 88)
def test_zero_network_isolation(monkeypatch):
    def fake_socket(*args, **kwargs):
        raise RuntimeError("Network call attempted during PPTX processing!")

    monkeypatch.setattr(socket, "socket", fake_socket)

    orig_bytes = (FIXTURES_DIR / "carrier_mixed.pptx").read_bytes()
    cleaned_bytes, report = clean_pptx_lossless(orig_bytes)
    assert report["changed"] is True


# 19. CLI Integration (Section 83)
def test_cli_inspect_clean_verify(tmp_path):
    p_orig = FIXTURES_DIR / "carrier_slide_text.pptx"
    p_cand = tmp_path / "carrier_slide_text.cleaned.pptx"

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


# 20. HTTP API Integration (Sections 84, 85, 86)
def test_http_api_pptx():
    import http.client
    import threading
    import server

    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()
        cand_bytes, _ = clean_pptx_lossless(orig_bytes)

        # POST /inspect
        payload_insp = {"file": base64.b64encode(orig_bytes).decode("ascii"), "name": "test.pptx"}
        conn.request("POST", "/inspect", body=json.dumps(payload_insp), headers={"Content-Type": "application/json"})
        resp_insp = conn.getresponse()
        data_insp = json.loads(resp_insp.read().decode("utf-8"))
        assert resp_insp.status == 200
        assert data_insp["ok"] is True

        # POST /clean
        payload_clean = {"file": base64.b64encode(orig_bytes).decode("ascii"), "name": "test.pptx"}
        conn.request("POST", "/clean", body=json.dumps(payload_clean), headers={"Content-Type": "application/json"})
        resp_clean = conn.getresponse()
        data_clean = json.loads(resp_clean.read().decode("utf-8"))
        assert resp_clean.status == 200
        assert data_clean["ok"] is True
        assert "cleaned" in data_clean
        assert data_clean["report"]["changed"] is True

        # POST /verify
        payload_ver = {
            "original": base64.b64encode(orig_bytes).decode("ascii"),
            "candidate": base64.b64encode(cand_bytes).decode("ascii"),
            "name": "test.pptx",
        }
        conn.request("POST", "/verify", body=json.dumps(payload_ver), headers={"Content-Type": "application/json"})
        resp_ver = conn.getresponse()
        data_ver = json.loads(resp_ver.read().decode("utf-8"))
        assert resp_ver.status == 200
        assert data_ver["ok"] is True
        assert data_ver["status"] == "PASS"
        assert data_ver["format"] == "pptx"
        assert data_ver["validation"]["structural_invariants_passed"] is True
    finally:
        conn.close()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# 21. Secondary Openability via Headless LibreOffice (Sections 89, 90)
def test_secondary_openability_libreoffice(tmp_path):
    soffice = Path(r"C:\Program Files\LibreOffice\program\soffice.com")
    if not soffice.exists():
        soffice = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    if not soffice.exists():
        pytest.skip("LibreOffice binary not found")

    orig_path = FIXTURES_DIR / "carrier_slide_text.pptx"
    orig_bytes = orig_path.read_bytes()
    cand_bytes, _ = clean_pptx_lossless(orig_bytes)

    cand_path = tmp_path / "cleaned.pptx"
    cand_path.write_bytes(cand_bytes)

    # Convert cleaned PPTX to PDF
    res = subprocess.run(
        [str(soffice), "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(cand_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"LibreOffice failed: {res.stderr}"
    pdf_path = tmp_path / "cleaned.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000


# 22. Negative Witnesses: Validation Fail-Closed (Sections 94, 95, 96, 97, 98)
def test_negative_witness_shape_id_drift():
    orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()
    pkg = PptxPackage(orig_bytes)
    slide1_xml = pkg.get_member("ppt/slides/slide1.xml").decode("utf-8")
    # Mutate shape ID from 2 to 999
    corrupted_xml = slide1_xml.replace('id="2"', 'id="999"', 1).encode("utf-8")

    cand_bytes = pkg.build_patched_package({"ppt/slides/slide1.xml": corrupted_xml})
    validator = PptxFidelityValidator(orig_bytes, cand_bytes)
    val_report = validator.validate()

    assert val_report.passed is False
    assert any("cNvPr id drift" in err for err in val_report.errors)


def test_negative_witness_slide_order_drift():
    orig_bytes = (FIXTURES_DIR / "carrier_mixed.pptx").read_bytes()
    pkg = PptxPackage(orig_bytes)
    pres_xml = pkg.get_member("ppt/presentation.xml").decode("utf-8")
    # Swap slide 1 and slide 2 r:id in sldIdLst
    corrupted_xml = pres_xml.replace('r:id="rId1"', 'r:id="TEMP_ID"')
    corrupted_xml = corrupted_xml.replace('r:id="rId2"', 'r:id="rId1"')
    corrupted_xml = corrupted_xml.replace('r:id="TEMP_ID"', 'r:id="rId2"').encode("utf-8")

    cand_bytes = pkg.build_patched_package({"ppt/presentation.xml": corrupted_xml})
    validator = PptxFidelityValidator(orig_bytes, cand_bytes)
    val_report = validator.validate()

    assert val_report.passed is False
    assert any("drift" in err for err in val_report.errors)


def test_negative_witness_slide_master_drift():
    orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()
    pkg = PptxPackage(orig_bytes)
    master_xml = pkg.get_member("ppt/slideMasters/slideMaster1.xml").decode("utf-8")
    corrupted_xml = master_xml.replace("Office Theme", "Corrupted Master Theme").encode("utf-8")

    cand_bytes = pkg.build_patched_package({"ppt/slideMasters/slideMaster1.xml": corrupted_xml})
    validator = PptxFidelityValidator(orig_bytes, cand_bytes)
    val_report = validator.validate()

    assert val_report.passed is False
    assert any("ppt/slideMasters/slideMaster1.xml" in err for err in val_report.errors)


def test_negative_witness_media_drift():
    orig_bytes = (FIXTURES_DIR / "carrier_mixed.pptx").read_bytes()
    pkg = PptxPackage(orig_bytes)
    corrupted_media = b"corrupted image bytes"

    cand_bytes = pkg.build_patched_package({"ppt/media/image1.png": corrupted_media})
    validator = PptxFidelityValidator(orig_bytes, cand_bytes)
    val_report = validator.validate()

    assert val_report.passed is False
    assert any("ppt/media/image1.png" in err for err in val_report.errors)


# 23. Signed or Macro Presentation Fail-Closed (Sections 34, 35)
def test_signed_or_macro_presentation_fail_closed():
    orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()

    # 1. Macro package: inject ppt/vbaProject.bin
    buf_m = io.BytesIO(orig_bytes)
    with zipfile.ZipFile(buf_m, "a") as zf:
        zf.writestr("ppt/vbaProject.bin", b"VBA_BINARY_CODE")
    macro_bytes = buf_m.getvalue()
    with pytest.raises(PptxError, match="Macro-enabled"):
        clean_pptx_lossless(macro_bytes)

    # 2. Signed package: inject ppt/_xmlsignatures/sig1.xml
    buf_s = io.BytesIO(orig_bytes)
    with zipfile.ZipFile(buf_s, "a") as zf:
        zf.writestr("ppt/_xmlsignatures/sig1.xml", b"<Signature/>")
    signed_bytes = buf_s.getvalue()
    with pytest.raises(PptxError, match="Digital signature"):
        clean_pptx_lossless(signed_bytes)


# 24. Cross-Format Verify Matrix (Section 103)
def test_cross_format_verify_matrix(tmp_path):
    pptx_path = FIXTURES_DIR / "carrier_slide_text.pptx"
    docx_path = Path("tests/fixtures/docx_body_carriers/synthetic_baseline.docx")
    xlsx_path = Path("tests/fixtures/xlsx_lossless/synthetic_baseline.xlsx")

    # Mismatched PPTX + DOCX
    code1 = cli_main(["verify", str(pptx_path), str(docx_path), "--json"])
    assert code1 != 0

    # Mismatched PPTX + XLSX
    code2 = cli_main(["verify", str(pptx_path), str(xlsx_path), "--json"])
    assert code2 != 0

    # Mismatched DOCX + PPTX
    code3 = cli_main(["verify", str(docx_path), str(pptx_path), "--json"])
    assert code3 != 0

    # Mismatched XLSX + PPTX
    code4 = cli_main(["verify", str(xlsx_path), str(pptx_path), "--json"])
    assert code4 != 0


# 25. Legacy Path No Double Cleaning (Section 79)
def test_legacy_path_no_double_cleaning(monkeypatch):
    import service.scripts.container_meta as cm

    orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()

    call_count = 0
    import pptx
    real_lossless = pptx.clean_pptx_lossless

    def counting_clean(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_lossless(*args, **kwargs)

    monkeypatch.setattr(pptx, "clean_pptx_lossless", counting_clean)
    cleaned_bytes, actions = cm.clean_pptx(orig_bytes)

    assert call_count == 1, f"Expected clean_pptx_lossless called once, got {call_count}"
    assert len(cleaned_bytes) > 0
    assert len(actions) > 0


# 26. Negative Witness: Nested Slide Relationship Drift (Sections 3, 4)
def test_negative_witness_nested_relationship_drift(tmp_path):
    orig_path = FIXTURES_DIR / "synthetic_clean_baseline.pptx"
    orig_bytes = orig_path.read_bytes()
    pkg = PptxPackage(orig_bytes)
    rels_part = "ppt/slides/_rels/slide1.xml.rels"
    orig_rels = pkg.get_member(rels_part)

    # Modify Target without altering slide XML
    bad_target_rels = orig_rels.replace(b"slideLayout1.xml", b"slideLayout99.xml")
    cand_bytes = pkg.build_patched_package({rels_part: bad_target_rels})

    # A. PptxFidelityValidator MUST fail
    val = PptxFidelityValidator(orig_bytes, cand_bytes)
    rep = val.validate()
    assert rep.passed is False
    assert any("Slide relationships drift in ppt/slides/_rels/slide1.xml.rels" in err for err in rep.errors)

    # B. CLI two-file verify MUST fail
    orig_file = tmp_path / "orig.pptx"
    cand_file = tmp_path / "cand.pptx"
    orig_file.write_bytes(orig_bytes)
    cand_file.write_bytes(cand_bytes)

    import io
    from contextlib import redirect_stdout
    out = io.StringIO()
    with redirect_stdout(out):
        ret = cli_main(["verify", str(orig_file), str(cand_file), "--json"])
    assert ret != 0
    cli_rep = json.loads(out.getvalue())
    assert cli_rep.get("status") == "FAIL"
    assert cli_rep.get("ok") is False

    # C. HTTP /verify MUST fail with 422
    import http.client
    import threading
    import server

    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        payload = {
            "original": base64.b64encode(orig_bytes).decode("ascii"),
            "candidate": base64.b64encode(cand_bytes).decode("ascii"),
            "name": "presentation.pptx",
        }
        conn.request("POST", "/verify", body=json.dumps(payload), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 422
        assert body.get("ok") is False
        assert body.get("status") == "FAIL"
        assert any("Slide relationships drift" in w for w in body.get("warnings", []))
    finally:
        conn.close()
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)

    # D. Id drift MUST fail
    bad_id_rels = orig_rels.replace(b"rId1", b"rId99")
    val_id = PptxFidelityValidator(orig_bytes, pkg.build_patched_package({rels_part: bad_id_rels}))
    assert val_id.validate().passed is False

    # E. TargetMode drift MUST fail
    bad_mode_rels = orig_rels.replace(b'slideLayout1.xml"', b'slideLayout1.xml" TargetMode="External"')
    val_mode = PptxFidelityValidator(orig_bytes, pkg.build_patched_package({rels_part: bad_mode_rels}))
    assert val_mode.validate().passed is False


# 27. Hyperlink, Image, and Layout Relationship Drift Detection (Section 3)
def test_relationship_targets_types_drift():
    orig_bytes = (FIXTURES_DIR / "synthetic_clean_baseline.pptx").read_bytes()
    pkg = PptxPackage(orig_bytes)
    rels_part = "ppt/slides/_rels/slide1.xml.rels"
    orig_rels = pkg.get_member(rels_part)

    # Hyperlink Target drift
    bad_hl = orig_rels.replace(b"https://example.com", b"https://malicious.com")
    val_hl = PptxFidelityValidator(orig_bytes, pkg.build_patched_package({rels_part: bad_hl}))
    rep_hl = val_hl.validate()
    assert rep_hl.passed is False
    assert any("Slide relationships drift" in e for e in rep_hl.errors)

    # Image relationship Target drift
    bad_img = orig_rels.replace(b"../media/image1.png", b"../media/image99.png")
    val_img = PptxFidelityValidator(orig_bytes, pkg.build_patched_package({rels_part: bad_img}))
    rep_img = val_img.validate()
    assert rep_img.passed is False
    assert any("Slide relationships drift" in e for e in rep_img.errors)

    # SlideLayout relationship Target drift
    bad_ly = orig_rels.replace(b"../slideLayouts/slideLayout1.xml", b"../slideLayouts/slideLayout99.xml")
    val_ly = PptxFidelityValidator(orig_bytes, pkg.build_patched_package({rels_part: bad_ly}))
    rep_ly = val_ly.validate()
    assert rep_ly.passed is False
    assert any("Slide relationships drift" in e for e in rep_ly.errors)


# 28. Package-Content-Driven Macro and Digital Signature Fail-Closed (Sections 10, 11, 12)
def test_macro_and_signature_fail_closed_package_driven():
    orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()
    pipeline = Pipeline()

    # 1. Macro package disguised as standard .pptx
    buf_vba = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(orig_bytes), "r") as z_in:
        with zipfile.ZipFile(buf_vba, "w", zipfile.ZIP_DEFLATED) as z_out:
            for item in z_in.infolist():
                z_out.writestr(item, z_in.read(item.filename))
            z_out.writestr("ppt/vbaProject.bin", b"fake vba binary payload")
    vba_bytes = buf_vba.getvalue()

    with pytest.raises(PptxError, match="Macro-enabled"):
        clean_pptx_lossless(vba_bytes)

    insp_vba = pipeline.inspect(vba_bytes, filename="sample.pptx", mode=ProcessingMode.SAFE)
    assert insp_vba.status == PipelineStatus.ERROR
    assert insp_vba.error_code == ErrorCode.INVALID_CONTAINER

    cleaned_vba, clean_rep_vba = pipeline.clean(vba_bytes, filename="sample.pptx", mode=ProcessingMode.SAFE)
    assert clean_rep_vba.status == PipelineStatus.ERROR
    assert clean_rep_vba.error_code == ErrorCode.INVALID_CONTAINER
    assert cleaned_vba == vba_bytes  # original bytes untouched

    # 2. Digitally signed package disguised as standard .pptx
    buf_sig = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(orig_bytes), "r") as z_in:
        with zipfile.ZipFile(buf_sig, "w", zipfile.ZIP_DEFLATED) as z_out:
            for item in z_in.infolist():
                z_out.writestr(item, z_in.read(item.filename))
            z_out.writestr("_xmlsignatures/origin.sigs", b"fake signature payload")
    sig_bytes = buf_sig.getvalue()

    with pytest.raises(PptxError, match="Digitally signed"):
        clean_pptx_lossless(sig_bytes)

    insp_sig = pipeline.inspect(sig_bytes, filename="sample.pptx", mode=ProcessingMode.SAFE)
    assert insp_sig.status == PipelineStatus.ERROR
    assert insp_sig.error_code == ErrorCode.INVALID_CONTAINER

    cleaned_sig, clean_rep_sig = pipeline.clean(sig_bytes, filename="sample.pptx", mode=ProcessingMode.SAFE)
    assert clean_rep_sig.status == PipelineStatus.ERROR
    assert clean_rep_sig.error_code == ErrorCode.INVALID_CONTAINER
    assert cleaned_sig == sig_bytes  # original bytes untouched


# 29. Strict Raw OPC Relationship Preservation Across Positive Clean (Section 14)
def test_raw_opc_relationship_preservation():
    orig_bytes = (FIXTURES_DIR / "carrier_slide_text.pptx").read_bytes()
    cleaned_bytes, rep = clean_pptx_lossless(orig_bytes)
    assert cleaned_bytes != orig_bytes

    orig_pkg = PptxPackage(orig_bytes)
    clean_pkg = PptxPackage(cleaned_bytes)

    # Verify every relationship part is strictly preserved at the raw OPC level
    rels_parts = [m for m in orig_pkg.member_order if "_rels" in m]
    assert len(rels_parts) >= 4, "Expected multiple relationship parts in package"

    for name in rels_parts:
        assert clean_pkg.has_member(name), f"Missing relationship member {name}"
        assert orig_pkg.get_hash(name) == clean_pkg.get_hash(name), f"{name} uncompressed SHA256 drift"
        assert orig_pkg.get_local_record(name) == clean_pkg.get_local_record(name), f"{name} raw local record drift"
        assert orig_pkg.get_compressed_hash(name) == clean_pkg.get_compressed_hash(name), f"{name} raw compressed payload drift"

        b_info = orig_pkg.zip_infos[name]
        a_info = clean_pkg.zip_infos[name]
        assert b_info.CRC == a_info.CRC, f"{name} CRC drift"
        assert b_info.compress_type == a_info.compress_type, f"{name} compress_type drift"
        assert b_info.compress_size == a_info.compress_size, f"{name} compress_size drift"
        assert b_info.file_size == a_info.file_size, f"{name} file_size drift"
        assert b_info.flag_bits == a_info.flag_bits, f"{name} flag_bits drift"
        assert b_info.date_time == a_info.date_time, f"{name} timestamp drift"

    # Member ordering invariant
    assert orig_pkg.member_order == clean_pkg.member_order


# 30. Target Slide XML Surgical Diff Verification (Section 15)
def test_target_slide_xml_surgical_diff():
    target_fixtures = [
        "carrier_slide_text.pptx",
        "carrier_multi_run.pptx",
        "carrier_table_text.pptx",
    ]
    for fn in target_fixtures:
        orig_bytes = (FIXTURES_DIR / fn).read_bytes()
        cleaned_bytes, _ = clean_pptx_lossless(orig_bytes)
        assert cleaned_bytes != orig_bytes

        orig_pkg = PptxPackage(orig_bytes)
        clean_pkg = PptxPackage(cleaned_bytes)

        for m in orig_pkg.member_order:
            if orig_pkg.get_hash(m) != clean_pkg.get_hash(m):
                # Must be a planned slide XML or metadata
                assert m.startswith("ppt/slides/slide") or m.startswith("docProps/"), f"Unexpected changed part {m}"

                if m.startswith("ppt/slides/slide"):
                    orig_xml = orig_pkg.get_member(m).decode("utf-8")
                    clean_xml = clean_pkg.get_member(m).decode("utf-8")

                    orig_lines = orig_xml.splitlines()
                    clean_lines = clean_xml.splitlines()
                    assert len(orig_lines) == len(clean_lines), f"Line count drift in {m}"

                    # For every differing line, prove it is an <a:t> line and everything around it is byte-exact
                    for line_idx, (ol, cl) in enumerate(zip(orig_lines, clean_lines)):
                        if ol != cl:
                            assert "<a:t>" in ol and "<a:t>" in cl, (
                                f"Non-text modification in {fn} -> {m} at line {line_idx + 1}: {ol!r} -> {cl!r}"
                            )
                            # Ensure prefix before <a:t> and suffix after </a:t> match byte-for-byte
                            prefix_o = ol[:ol.index("<a:t>")]
                            prefix_c = cl[:cl.index("<a:t>")]
                            suffix_o = ol[ol.rindex("</a:t>"):]
                            suffix_c = cl[cl.rindex("</a:t>"):]
                            assert prefix_o == prefix_c, f"Prefix drift before <a:t> in {m}"
                            assert suffix_o == suffix_c, f"Suffix drift after </a:t> in {m}"


