"""Tests for Phase 5: OPC/OOXML Package Preservation."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import zipfile
import pytest

from service.scripts.docx import clean_docx_lossless
from service.scripts.docx.package import DocxPackage
from service.scripts.docx.patcher import DocxPatcher, _prune_dangling_relationships
from service.scripts.docx.mutation_plan import DocxMutationPlan, PartDropMutation, TextCodepointMutation


def _build_test_docx_package() -> bytes:
    """Build a synthetic test DOCX package with various parts, metadata, rels, and customXml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # 1. [Content_Types].xml with both double and single quotes
        ct_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName='/customXml/item1.xml' ContentType='application/xml'/>
</Types>"""
        zf.writestr("[Content_Types].xml", ct_xml)

        # 2. _rels/.rels
        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="customXml/item1.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/>
</Relationships>"""
        zf.writestr("_rels/.rels", root_rels)

        # 3. word/document.xml with invisible watermark carrier U+200B
        doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Văn bản\u200Bthử nghiệm</w:t></w:r></w:p>
  </w:body>
</w:document>"""
        zf.writestr("word/document.xml", doc_xml)

        # 4. docProps/core.xml
        core_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator>Author Test</dc:creator>
</cp:coreProperties>"""
        zf.writestr("docProps/core.xml", core_xml)

        # 5. customXml/item1.xml
        custom_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><root><item/></root>"""
        zf.writestr("customXml/item1.xml", custom_xml)

        # 6. Untargeted auxiliary part that must have 100% identical SHA256
        zf.writestr("word/fontTable.xml", "<w:fonts xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>")

    return buf.getvalue()


def test_member_order_preservation():
    """Verify that member ordering in the ZIP container is preserved exactly."""
    raw = _build_test_docx_package()
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        orig_order = zf.namelist()

    cleaned, report = clean_docx_lossless(raw)

    with zipfile.ZipFile(io.BytesIO(cleaned), "r") as zf:
        cleaned_order = zf.namelist()

    # customXml/item1.xml is dropped, all other members must preserve their relative order
    expected_order = [n for n in orig_order if n != "customXml/item1.xml"]
    assert cleaned_order == expected_order


def test_non_target_hash_immutability():
    """Verify that parts not modified by the mutation plan retain exact byte-for-byte SHA256."""
    raw = _build_test_docx_package()
    cleaned, report = clean_docx_lossless(raw)

    orig_pkg = DocxPackage(raw)
    cleaned_pkg = DocxPackage(cleaned)

    # word/fontTable.xml was not in the mutation plan
    assert orig_pkg.get_hash("word/fontTable.xml") == cleaned_pkg.get_hash("word/fontTable.xml")
    assert orig_pkg.get_member("word/fontTable.xml") == cleaned_pkg.get_member("word/fontTable.xml")


def test_zipfile_testzip_integrity():
    """Verify that the cleaned ZIP container passes testzip() with zero corruption."""
    raw = _build_test_docx_package()
    cleaned, report = clean_docx_lossless(raw)

    with zipfile.ZipFile(io.BytesIO(cleaned), "r") as zf:
        assert zf.testzip() is None


def test_external_and_root_relationships_preserved():
    """Ensure External relationships (URLs) and root references are never dropped when pruning rels."""
    rels_content = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target='customXml/item1.xml'/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://deepmind.google" TargetMode="External"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="/docProps/core.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/package/2006/relationships/root" Target="/"/>
</Relationships>""".encode("utf-8")

    kept_names = {"docProps/core.xml", "word/document.xml"}
    new_rels, count = _prune_dangling_relationships("_rels/.rels", rels_content, kept_names)

    # customXml/item1.xml should be pruned (count = 1)
    assert count == 1
    new_text = new_rels.decode("utf-8")
    assert "customXml/item1.xml" not in new_text
    assert "https://deepmind.google" in new_text
    assert "docProps/core.xml" in new_text
    assert 'Target="/"' in new_text


def test_content_types_override_cleanup():
    """Ensure [Content_Types].xml properly drops Override tags with either single or double quotes."""
    raw = _build_test_docx_package()
    cleaned, report = clean_docx_lossless(raw)

    with zipfile.ZipFile(io.BytesIO(cleaned), "r") as zf:
        ct_content = zf.read("[Content_Types].xml").decode("utf-8")

    # customXml/item1.xml override was with single quotes in _build_test_docx_package
    assert "customXml/item1.xml" not in ct_content
    assert "/word/document.xml" in ct_content
    assert "/docProps/core.xml" in ct_content


def test_raw_opc_zip_entry_preservation():
    """Verify bit-for-bit raw ZIP preservation for all unchanged OPC members.
    
    Verifies that unchanged entries preserve:
    - raw decompressed payload SHA-256
    - raw compressed payload SHA-256
    - CRC-32
    - compression method (compress_type)
    - flag_bits (e.g. 6 == 6)
    - external_attr (e.g. 0 == 0)
    - internal_attr
    - date_time
    - extra field (e.g. alignment padding)
    - comment
    """
    repo_root = Path(__file__).resolve().parent.parent
    golden_path = repo_root / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
    if not golden_path.exists():
        pytest.skip("01_GOLDEN_ORIGINAL_UNTOUCHED.docx not found")

    golden_bytes = golden_path.read_bytes()
    clean_bytes, report = clean_docx_lossless(golden_bytes)
    assert report["fidelity_guaranteed"] is True

    orig_pkg = DocxPackage(golden_bytes)
    clean_pkg = DocxPackage(clean_bytes)

    with zipfile.ZipFile(io.BytesIO(golden_bytes), "r") as z_orig, \
         zipfile.ZipFile(io.BytesIO(clean_bytes), "r") as z_clean:

        orig_infos = {info.filename: info for info in z_orig.infolist()}
        clean_infos = {info.filename: info for info in z_clean.infolist()}

        planned_changed = {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"}

        for name, o_info in orig_infos.items():
            if name in planned_changed:
                continue

            assert name in clean_infos, f"Member '{name}' missing from cleaned package"
            c_info = clean_infos[name]

            # 1. Uncompressed payload hash
            payload_sha256_before = orig_pkg.get_hash(name)
            payload_sha256_after = clean_pkg.get_hash(name)
            assert payload_sha256_before == payload_sha256_after, f"Payload hash mismatch in {name}"

            # 2. Raw compressed payload hash
            compressed_payload_sha256_before = orig_pkg.get_compressed_hash(name)
            compressed_payload_sha256_after = clean_pkg.get_compressed_hash(name)
            assert compressed_payload_sha256_before == compressed_payload_sha256_after, (
                f"Raw compressed payload hash mismatch in {name}: "
                f"{compressed_payload_sha256_before} != {compressed_payload_sha256_after}"
            )

            # 3. CRC-32
            assert o_info.CRC == c_info.CRC, f"CRC mismatch in {name}"

            # 4. Compression method
            assert o_info.compress_type == c_info.compress_type, f"compress_type mismatch in {name}"

            # 5. flag_bits
            assert o_info.flag_bits == c_info.flag_bits, f"flag_bits mismatch in {name}"

            # 6. external_attr
            assert o_info.external_attr == c_info.external_attr, f"external_attr mismatch in {name}"

            # 7. internal_attr
            assert o_info.internal_attr == c_info.internal_attr, f"internal_attr mismatch in {name}"

            # 8. date_time
            assert o_info.date_time == c_info.date_time, f"date_time mismatch in {name}"

            # 9. extra (OPC padding / alignment fields)
            assert o_info.extra == c_info.extra, f"extra field mismatch in {name}"

            # 10. comment
            assert o_info.comment == c_info.comment, f"comment mismatch in {name}"


def test_non_target_part_hashes_evidence_matches_binaries():
    """Verify that evidence/non_target_part_hashes.json exactly matches the physical files.
    
    Prevents stale, documentation-copied, or mismatched digest values in release evidence.
    """
    import json
    repo_root = Path(__file__).resolve().parent.parent
    golden_path = repo_root / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
    candidate_path = repo_root / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"
    evidence_path = repo_root / "artifacts" / "final_acceptance" / "non_target_part_hashes.json"

    if not golden_path.exists() or not candidate_path.exists() or not evidence_path.exists():
        pytest.skip("Required golden, candidate, or evidence file missing")

    golden_bytes = golden_path.read_bytes()
    candidate_bytes = candidate_path.read_bytes()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    g_pkg = DocxPackage(golden_bytes)
    c_pkg = DocxPackage(candidate_bytes)

    with zipfile.ZipFile(io.BytesIO(golden_bytes), "r") as z_golden, \
         zipfile.ZipFile(io.BytesIO(candidate_bytes), "r") as z_candidate:

        for entry in evidence["parts"]:
            name = entry["name"]

            # Verify reported decompressed hashes against actual decompressed bytes
            actual_g_uncomp = hashlib.sha256(z_golden.read(name)).hexdigest()
            actual_c_uncomp = hashlib.sha256(z_candidate.read(name)).hexdigest()
            assert entry["golden_sha256"] == actual_g_uncomp, f"Stale golden_sha256 for {name} in evidence"
            assert entry["candidate_sha256"] == actual_c_uncomp, f"Stale candidate_sha256 for {name} in evidence"

            # Verify reported raw compressed hashes against actual compressed bytes
            actual_g_comp = g_pkg.get_compressed_hash(name)
            actual_c_comp = c_pkg.get_compressed_hash(name)
            assert entry["golden_raw_compressed_sha256"] == actual_g_comp, f"Stale golden_raw_compressed_sha256 for {name}"
            assert entry["candidate_raw_compressed_sha256"] == actual_c_comp, f"Stale candidate_raw_compressed_sha256 for {name}"

            # For unchanged non-target parts, verify strict identity
            if not entry["in_plan"]:
                assert entry["uncompressed_match"] is True
                assert entry["compressed_match"] is True
                assert entry["golden_sha256"] == entry["candidate_sha256"]
                assert entry["golden_raw_compressed_sha256"] == entry["candidate_raw_compressed_sha256"]

