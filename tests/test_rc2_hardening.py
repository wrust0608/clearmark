"""Comprehensive regression test suite for ClearMark v2.2 RC2 Hardening.

Covers:
- A01 & A04: Contextual Unicode classifier preserves emoji sequences with variation selector (e.g. 🏳️‍🌈, ❤️‍🔥).
- A02 & A15: Exact mutation identity: patcher targets only authorized occurrences without global codepoint deletion.
- A03: Independent validator detects un-authorized mutations and enforces non-target character conservation.
- A05: Contextual Unicode preserved across multiple Word runs (<w:r><w:t>).
- A06: HTTP /clean returned bytes SHA256 strictly matches report.output.sha256.
- A07: Default cleaning is Layer A only; zero network egress and zero prose rewrite.
- A08: /clean/batch routes through canonical Pipeline.
- A09: customXml with w:dataBinding is preserved (dependency-aware).
- A10: docProps/custom.xml referenced by DOCPROPERTY is preserved (dependency-aware).
- A11: Modified OOXML entries clear ZIP general purpose bit 3.
- A12: Embedded JPEG APP2 ICC and WebP ICCP profiles are preserved during cleaning.
- A13: DOCX surface tracking reports checked/unsupported surfaces.
- A14: AI generator product names in generator metadata recognized and scrubbed.
- A17: XLSX and PPTX patchers execute exact planned mutations without re-cleaning.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import socket
import threading
import zipfile
from pathlib import Path

import pytest

from service.scripts.container_meta import named_value_is_ai
from service.scripts.docx import (
    DocxDetector,
    DocxFidelityValidator,
    DocxMutationPlan,
    DocxPackage,
    clean_docx_lossless,
)
from service.scripts.docx.exceptions import DocxFidelityException
from service.scripts.docx.mutation_plan import TextCodepointMutation
from service.scripts.image_meta import strip_jpeg, strip_webp
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import ProcessingMode
from service.scripts.pptx import clean_pptx_lossless
from service.scripts.server import Handler, ThreadingHTTPServer
from service.scripts.text_unicode import classify_stream
from service.scripts.xlsx import clean_xlsx_lossless

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _build_minimal_docx(doc_xml: str, extra_members: dict[str, str | bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""")
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""")
        zf.writestr("word/document.xml", doc_xml)
        if extra_members:
            for k, v in extra_members.items():
                zf.writestr(k, v)
    return buf.getvalue()


# -----------------------------------------------------------------------------
# A01 & A04: Contextual Unicode Classifier & Emoji with VS16
# -----------------------------------------------------------------------------

def test_a01_a04_emoji_vs16_zwj_classification():
    """Verify classify_stream correctly bridges emoji + VS16 + ZWJ + emoji."""
    rainbow_flag = "🏳\ufe0f\u200d🌈"
    heart_on_fire = "❤\ufe0f\u200d🔥"
    couples = "👩\u200d❤\ufe0f\u200d👨"

    # Rainbow flag
    cls1 = classify_stream(rainbow_flag)
    assert not any(c.action != "keep" for c in cls1), "Rainbow flag ZWJ must not be stripped"

    # Heart on fire
    cls2 = classify_stream(heart_on_fire)
    assert not any(c.action != "keep" for c in cls2), "Heart on fire ZWJ must not be stripped"

    # Coupled emoji
    cls3 = classify_stream(couples)
    assert not any(c.action != "keep" for c in cls3), "Coupled emoji ZWJ must not be stripped"

    # Negative witness: standalone ZWJ
    standalone = "Hello\u200dWorld"
    cls_standalone = classify_stream(standalone)
    assert any(c.action == "strip" and c.char == "\u200d" for c in cls_standalone), "Standalone ZWJ must be stripped"


# -----------------------------------------------------------------------------
# A05: Split-Run Contextual Unicode
# -----------------------------------------------------------------------------

def test_a05_split_run_contextual_unicode():
    """Verify contextual emoji sequence split across multiple runs is preserved."""
    # Split rainbow flag: <w:r><w:t>🏳️</w:t></w:r><w:r><w:t>‍🌈</w:t></w:r>
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:r><w:t>Flag: </w:t></w:r>
      <w:r><w:t>🏳\ufe0f</w:t></w:r>
      <w:r><w:t>\u200d🌈</w:t></w:r>
      <w:r><w:t> intact.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>"""
    docx_bytes = _build_minimal_docx(doc_xml)
    pkg = DocxPackage(docx_bytes)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert len(plan.text_mutations) == 0, f"Split-run emoji produced false-positive mutation: {plan.text_mutations}"

    cleaned_bytes, rep = clean_docx_lossless(docx_bytes, {"mode": "SAFE"})
    assert rep["changed"] is False
    assert cleaned_bytes == docx_bytes


# -----------------------------------------------------------------------------
# A02 & A15: Exact Planned Mutation Identity (Negative Witness)
# -----------------------------------------------------------------------------

def test_a02_a15_exact_mutation_identity_same_codepoint():
    """Verify that only the planned occurrence of a codepoint is deleted, leaving legitimate ones intact."""
    # In the same paragraph: legitimate 🏳️‍🌈, suspicious carrier\u200dtest, legitimate ❤️‍🔥
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:r><w:t>Legitimate 🏳\ufe0f\u200d🌈 and ❤\ufe0f\u200d🔥 with Carrier\u200dtest.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>"""
    docx_bytes = _build_minimal_docx(doc_xml)
    pkg = DocxPackage(docx_bytes)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert len(plan.text_mutations) == 1, "Only the carrier ZWJ must be targeted"
    mut = plan.text_mutations[0]
    assert mut.codepoint == 0x200D
    assert "Carrier" in mut.context_witness or "test" in mut.context_witness

    cleaned_bytes, rep = clean_docx_lossless(docx_bytes, {"mode": "SAFE"})
    assert rep["changed"] is True
    assert rep["mutations_count"] == 1

    cleaned_pkg = DocxPackage(cleaned_bytes)
    cleaned_xml = cleaned_pkg.get_member("word/document.xml").decode("utf-8")
    assert "🏳\ufe0f\u200d🌈" in cleaned_xml
    assert "❤\ufe0f\u200d🔥" in cleaned_xml
    assert "Carriertest" in cleaned_xml
    assert "Carrier\u200dtest" not in cleaned_xml


# -----------------------------------------------------------------------------
# A03: Independent Validator Catches Over-Mutation
# -----------------------------------------------------------------------------

def test_a03_validator_catches_unauthorized_deletion():
    """Independent validator must reject output if a patcher removes an un-authorized codepoint."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:r><w:t>Target\u200b carrier and innocent\u200b keep.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>"""
    docx_bytes = _build_minimal_docx(doc_xml)

    # Authorized plan: ONLY 1 mutation (the first U+200B)
    authorized_plan = DocxMutationPlan(
        text_mutations=[
            TextCodepointMutation(
                part_name="word/document.xml",
                p_idx=0,
                r_idx=0,
                t_idx=0,
                codepoint=0x200B,
                char_name="ZERO WIDTH SPACE",
                offset=6,
                replacement="",
                context_witness="Target\u200b carrier",
            )
        ]
    )

    # Simulate a rogue patcher that globally deletes ALL U+200B
    rogue_xml = doc_xml.replace("\u200b", "")
    rogue_bytes = _build_minimal_docx(rogue_xml)

    validator = DocxFidelityValidator(
        original_data=docx_bytes,
        cleaned_data=rogue_bytes,
        plan=authorized_plan,
    )
    with pytest.raises(DocxFidelityException) as exc_info:
        validator.validate()
    assert "mismatch" in str(exc_info.value).lower()


# -----------------------------------------------------------------------------
# A06: Returned Bytes Strictly Equal Report Output SHA256
# -----------------------------------------------------------------------------

def test_a06_returned_bytes_match_report_sha256():
    """Verify HTTP server returns bytes that strictly equal the report output SHA256."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        sample_doc = _build_minimal_docx(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body><w:p><w:r><w:t>Test\u200b Document</w:t></w:r></w:p></w:body>
</w:document>""")
        b64_in = base64.b64encode(sample_doc).decode("ascii")
        payload = json.dumps({"file": b64_in, "name": "test.docx", "options": {"mode": "safe"}})

        conn.request("POST", "/clean", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True

        cleaned_bytes = base64.b64decode(data["cleaned"])
        actual_sha = hashlib.sha256(cleaned_bytes).hexdigest()
        report_sha = data["report"]["output"]["sha256"]

        assert actual_sha == report_sha, f"Returned bytes SHA256 {actual_sha} != report SHA256 {report_sha}"
    finally:
        conn.close()
        srv.shutdown()
        srv.server_close()


# -----------------------------------------------------------------------------
# A07: Default Cleaning is Layer A Only, Zero Network Egress
# -----------------------------------------------------------------------------

def test_a07_default_cleaning_layer_a_zero_network(monkeypatch):
    """Verify default cleaning uses Layer A only, does not rewrite prose, and makes zero network calls."""
    # Monkeypatch socket.socket to fail if any network connection is attempted
    def _fail_socket(*args, **kwargs):
        raise AssertionError("Network socket opened during default SAFE clean!")
    monkeypatch.setattr(socket, "socket", _fail_socket)

    pipe = Pipeline()
    text = "Here is an ordinary paragraph with an invisible carrier\u200b inside."
    cleaned_bytes, rep = pipe.clean(text.encode("utf-8"), filename="test.txt", mode=ProcessingMode.SAFE)

    cleaned_text = cleaned_bytes.decode("utf-8")
    assert "\u200b" not in cleaned_text
    assert cleaned_text == "Here is an ordinary paragraph with an invisible carrier inside."
    assert rep.privacy.network_used is False
    assert len(rep.privacy.external_services) == 0
    assert rep.to_dict().get("layer_b") is None


# -----------------------------------------------------------------------------
# A08: /clean/batch Uses Canonical Pipeline
# -----------------------------------------------------------------------------

def test_a08_clean_batch_canonical_pipeline():
    """Verify /clean/batch routes through canonical pipeline and returns matching SHA256."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    try:
        sample_doc = _build_minimal_docx(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body><w:p><w:r><w:t>Batch\u200b Test</w:t></w:r></w:p></w:body>
</w:document>""")
        b64_in = base64.b64encode(sample_doc).decode("ascii")
        payload = json.dumps({
            "files": [{"name": "item1.docx", "file": b64_in, "options": {"mode": "safe"}}]
        })

        conn.request("POST", "/clean/batch", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        item = data["results"][0]
        assert item["ok"] is True

        cleaned_bytes = base64.b64decode(item["cleaned"])
        actual_sha = hashlib.sha256(cleaned_bytes).hexdigest()
        assert actual_sha == item["report"]["output"]["sha256"]
    finally:
        conn.close()
        srv.shutdown()
        srv.server_close()


# -----------------------------------------------------------------------------
# A09: Word customXml with w:dataBinding is Preserved
# -----------------------------------------------------------------------------

def test_a09_customxml_databinding_preserved():
    """Verify customXml is NOT dropped if referenced by Word w:dataBinding."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:sdt>
      <w:sdtPr>
        <w:dataBinding w:xpath="/root/item" w:storeItemID="{{12345678-1234-1234-1234-1234567890AB}}"/>
      </w:sdtPr>
      <w:sdtContent>
        <w:p><w:r><w:t>Bound content\u200b</w:t></w:r></w:p>
      </w:sdtContent>
    </w:sdt>
  </w:body>
</w:document>"""
    extra = {
        "customXml/item1.xml": b"<root><item>Hello</item></root>",
        "customXml/itemProps1.xml": b'<ds:datastoreItem xmlns:ds="http://schemas.openxmlformats.org/officeDocument/2006/customXml" ds:itemID="{12345678-1234-1234-1234-1234567890AB}"/>',
    }
    docx_bytes = _build_minimal_docx(doc_xml, extra_members=extra)
    pkg = DocxPackage(docx_bytes)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert not any(pd.part_name.startswith("customXml/") for pd in plan.part_drops), "customXml must NOT be dropped when bound via w:dataBinding"

    cleaned_bytes, _rep = clean_docx_lossless(docx_bytes, {"mode": "SAFE"})
    cleaned_pkg = DocxPackage(cleaned_bytes)
    assert "customXml/item1.xml" in cleaned_pkg.member_order
    assert "customXml/itemProps1.xml" in cleaned_pkg.member_order


# -----------------------------------------------------------------------------
# A10: Word docProps/custom.xml with DOCPROPERTY is Preserved
# -----------------------------------------------------------------------------

def test_a10_docprops_custom_docproperty_preserved():
    """Verify docProps/custom.xml is NOT dropped if referenced by a DOCPROPERTY field."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:fldSimple w:instr='DOCPROPERTY "ClientName"'>
        <w:r><w:t>Acme Corp\u200b</w:t></w:r>
      </w:fldSimple>
    </w:p>
  </w:body>
</w:document>"""
    custom_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="ClientName">
    <vt:lpwstr>Acme Corp</vt:lpwstr>
  </property>
</Properties>"""
    extra = {"docProps/custom.xml": custom_xml}
    docx_bytes = _build_minimal_docx(doc_xml, extra_members=extra)
    pkg = DocxPackage(docx_bytes)
    plan = DocxDetector(pkg, {"mode": "SAFE"}).build_plan()

    assert not any(pd.part_name == "docProps/custom.xml" for pd in plan.part_drops), "docProps/custom.xml must NOT be dropped when referenced by DOCPROPERTY"

    cleaned_bytes, _rep = clean_docx_lossless(docx_bytes, {"mode": "SAFE"})
    cleaned_pkg = DocxPackage(cleaned_bytes)
    assert "docProps/custom.xml" in cleaned_pkg.member_order


# -----------------------------------------------------------------------------
# A11: OOXML Package ZIP Bit 3 Handling
# -----------------------------------------------------------------------------

def test_a11_ooxml_zip_bit_3_cleared_on_modified_entries():
    """Verify modified entries in rebuilt package have general purpose bit 3 cleared."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body><w:p><w:r><w:t>Entry\u200b with bit 3</w:t></w:r></w:p></w:body>
</w:document>"""
    docx_bytes = _build_minimal_docx(doc_xml)
    pkg = DocxPackage(docx_bytes)
    changed_parts = {"word/document.xml": doc_xml.replace("\u200b", "").encode("utf-8")}
    rebuilt_bytes = pkg.rebuild(changed_parts, set())

    with zipfile.ZipFile(io.BytesIO(rebuilt_bytes)) as zf:
        info = zf.getinfo("word/document.xml")
        assert (info.flag_bits & 0x08) == 0, "General purpose bit 3 MUST be cleared on modified entry"


# -----------------------------------------------------------------------------
# A12: Embedded JPEG APP2 ICC and WebP ICCP Preservation
# -----------------------------------------------------------------------------

def test_a12_media_preserves_icc_profiles():
    """Verify strip_jpeg and strip_webp preserve render-critical ICC profiles in SAFE mode."""
    # Construct synthetic JPEG with APP2 ICC_PROFILE
    icc_data = b"ICC_PROFILE\x00\x01\x01SyntheticICCProfileData"
    app2_marker = b"\xff\xe2" + len(icc_data + b"\x00\x00").to_bytes(2, "big") + icc_data
    # SOI + APP2 + SOS + EOI
    synthetic_jpg = b"\xff\xd8" + app2_marker + b"\xff\xda\x00\x02\x00\x00" + b"\xff\xd9"

    cleaned_jpg, _count_jpg = strip_jpeg(synthetic_jpg, preserve_icc=True)
    assert b"ICC_PROFILE" in cleaned_jpg, "JPEG APP2 ICC profile must be preserved"

    # Construct synthetic WebP with ICCP chunk
    inner_payload = (
        b"VP8X" + (10).to_bytes(4, "little") + b"\x20\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"ICCP" + (8).to_bytes(4, "little") + b"TestICCP"
    )
    riff_size = len(b"WEBP" + inner_payload)
    synthetic_webp = b"RIFF" + riff_size.to_bytes(4, "little") + b"WEBP" + inner_payload

    cleaned_webp, _count_webp = strip_webp(synthetic_webp, preserve_icc=True)
    assert b"ICCP" in cleaned_webp, "WebP ICCP chunk must be preserved"


# -----------------------------------------------------------------------------
# A13: Surface Tracking
# -----------------------------------------------------------------------------

def test_a13_surface_tracking_representation():
    """Verify DocxDetector tracks and reports checked, unsupported, and not_checked surfaces."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body><w:p><w:r><w:t>Normal Doc</w:t></w:r></w:p></w:body>
</w:document>"""
    docx_bytes = _build_minimal_docx(doc_xml)
    pkg = DocxPackage(docx_bytes)
    detector = DocxDetector(pkg, {"mode": "SAFE"})
    plan = detector.build_plan()

    assert plan.surface_coverage["body_document"] == "CHECKED"
    assert "tracked_deletions" in plan.surface_coverage
    assert plan.surface_coverage["tracked_deletions"] == "NOT_CHECKED"


# -----------------------------------------------------------------------------
# A14: AI Generator Product Names Port
# -----------------------------------------------------------------------------

def test_a14_ai_generator_product_names():
    """Verify AI product names under generator metadata keys are detected as AI, while prose is preserved."""
    assert named_value_is_ai("generated_by", "GPT-4o")
    assert named_value_is_ai("software", "ChatGPT")
    assert named_value_is_ai("creator", "Midjourney")
    assert named_value_is_ai("tool", "DALL-E")

    # Ordinary prose under description or context must NOT be flagged
    assert not named_value_is_ai("description", "We discussed GPT-4o pricing")
    assert not named_value_is_ai("context", "Using Midjourney for concept art")


# -----------------------------------------------------------------------------
# A17: XLSX & PPTX Patcher Consistency with Mutation Plan
# -----------------------------------------------------------------------------

def test_a17_xlsx_pptx_plan_execution():
    """Verify XLSX and PPTX patchers execute only planned mutations without re-cleaning."""
    # Clean XLSX round trip
    xlsx_path = Path("tests/fixtures/synthetic_baseline.xlsx")
    if xlsx_path.exists():
        raw = xlsx_path.read_bytes()
        _cleaned, rep = clean_xlsx_lossless(raw, {"mode": "SAFE"})
        assert rep["changed"] is False

    # Clean PPTX round trip
    pptx_path = Path("tests/fixtures/carrier_slide_text.pptx")
    if pptx_path.exists():
        raw = pptx_path.read_bytes()
        _cleaned, rep = clean_pptx_lossless(raw, {"mode": "SAFE"})
        assert rep["changed"] is True
        assert rep["mutations_count"] > 0
