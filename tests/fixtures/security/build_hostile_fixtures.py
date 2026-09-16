"""tests/fixtures/security/build_hostile_fixtures.py

Deterministic synthetic hostile fixture builder for Phase 9 Malformed File Hardening.
Builds compact, reproducible hostile archives and hostile XML parts without requiring
large committed binary blobs.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional


FIXTURES_DIR = Path(__file__).resolve().parent


def build_raw_zip(
    entries: List[Dict[str, Any]],
    *,
    eocd_comment: bytes = b"",
    cd_offset_override: Optional[int] = None,
    cd_size_override: Optional[int] = None,
    disk_num: int = 0,
    cd_disk: int = 0,
    total_entries_override: Optional[int] = None,
    zip64_locator: bool = False,
    overlap_second_member: bool = False,
) -> bytes:
    """Construct deterministic raw ZIP byte streams with full field control."""
    local_records: List[bytes] = []
    cd_records: List[bytes] = []
    local_offsets: List[int] = []

    pos = 0
    for idx, e in enumerate(entries):
        name_bytes = e.get("name_bytes") or e["name"].encode("utf-8")
        loc_name_bytes = e.get("local_name_bytes", name_bytes)
        uncomp = e.get("data", b"")
        comp_method = e.get("comp_method", 8)  # default DEFLATE
        flags = e.get("flags", 0)
        crc = e.get("crc", zlib.crc32(uncomp) & 0xFFFFFFFF)
        external_attr = e.get("external_attr", 0)
        csize_override = e.get("csize_override")
        usize_override = e.get("usize_override")
        lhoff_override = e.get("lhoff_override")

        # Compress payload
        if comp_method == 0:
            payload = uncomp
        elif comp_method == 8:
            payload = zlib.compress(uncomp)[2:-4]  # raw deflate stream
        else:
            payload = uncomp  # dummy payload for unsupported compression

        if e.get("truncate_payload"):
            payload = payload[: max(1, len(payload) // 2)]

        csize = len(payload) if csize_override is None else csize_override
        usize = len(uncomp) if usize_override is None else usize_override

        lhoff = pos if lhoff_override is None else lhoff_override

        # If testing overlapping members, member 1 and 2 start at overlapping offsets
        if overlap_second_member and idx == 1:
            lhoff = local_offsets[0] + 10  # overlaps into member 0!

        local_offsets.append(lhoff)

        # Local Header (30 bytes + name + extra)
        loc_hdr = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,  # signature
            20,          # version needed
            flags,
            comp_method,
            0x4E21,      # mtime
            0x5821,      # mdate
            crc,
            csize,
            usize,
            len(loc_name_bytes),
            0,           # extra len
        )
        local_rec = loc_hdr + loc_name_bytes + payload
        local_records.append(local_rec)
        pos += len(local_rec)

    # Central Directory records
    cd_start = pos if cd_offset_override is None else cd_offset_override
    for idx, e in enumerate(entries):
        name_bytes = e.get("name_bytes") or e["name"].encode("utf-8")
        uncomp = e.get("data", b"")
        comp_method = e.get("comp_method", 8)
        flags = e.get("flags", 0)
        crc = e.get("crc", zlib.crc32(uncomp) & 0xFFFFFFFF)
        external_attr = e.get("external_attr", 0)
        csize_override = e.get("csize_override")
        usize_override = e.get("usize_override")
        lhoff_override = e.get("lhoff_override")

        if comp_method == 0:
            payload_len = len(uncomp)
        elif comp_method == 8:
            payload_len = len(zlib.compress(uncomp)[2:-4])
        else:
            payload_len = len(uncomp)

        if e.get("truncate_payload"):
            payload_len = max(1, payload_len // 2)

        csize = payload_len if csize_override is None else csize_override
        usize = len(uncomp) if usize_override is None else usize_override
        lhoff = local_offsets[idx] if lhoff_override is None else lhoff_override

        cd_hdr = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,  # signature
            20,          # made by
            20,          # ver needed
            flags,
            comp_method,
            0x4E21,
            0x5821,
            crc,
            csize,
            usize,
            len(name_bytes),
            0,           # extra len
            0,           # comment len
            0,           # disk num
            0,           # int attr
            external_attr,
            lhoff,
        )
        cd_rec = cd_hdr + name_bytes
        cd_records.append(cd_rec)
        pos += len(cd_rec)

    raw_cd = b"".join(cd_records)
    cd_size = len(raw_cd) if cd_size_override is None else cd_size_override
    total_entries = len(entries) if total_entries_override is None else total_entries_override

    # ZIP64 locator injection if requested
    zip64_bytes = b""
    if zip64_locator:
        zip64_bytes = struct.pack(
            "<IIQI",
            0x07064B50,  # ZIP64 locator signature PK\x06\x07
            0,           # disk with ZIP64 EOCD
            cd_start + cd_size,
            1,           # total disks
        )

    # EOCD record (22 bytes + comment)
    eocd = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        disk_num,
        cd_disk,
        total_entries,
        total_entries,
        cd_size,
        cd_start,
        len(eocd_comment),
    ) + eocd_comment

    return b"".join(local_records) + raw_cd + zip64_bytes + eocd


def make_minimal_docx(custom_parts: Dict[str, bytes] | None = None) -> bytes:
    """Build a minimal valid DOCX package with optional part replacements."""
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        b'  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        b'  <Default Extension="xml" ContentType="application/xml"/>\n'
        b'  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        b'</Types>'
    )
    rels = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        b'  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        b'</Relationships>'
    )
    doc_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        b'  <w:body>\n'
        b'    <w:p><w:r><w:t>Hello World</w:t></w:r></w:p>\n'
        b'  </w:body>\n'
        b'</w:document>'
    )
    parts = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": rels,
        "word/document.xml": doc_xml,
    }
    if custom_parts:
        parts.update(custom_parts)

    entries = [{"name": k, "data": v, "comp_method": 8} for k, v in parts.items()]
    return build_raw_zip(entries)


def generate_all_fixtures() -> Dict[str, Dict[str, Any]]:
    """Build all deterministic hostile fixtures and return manifest dictionary."""
    manifest: Dict[str, Dict[str, Any]] = {}
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    def register(filename: str, data: bytes, threat_id: str, rule_id: str, desc: str) -> None:
        target = FIXTURES_DIR / filename
        target.write_bytes(data)
        manifest[filename] = {
            "threat_id": threat_id,
            "rule_id": rule_id,
            "description": desc,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    # 1. ZipSlip: Parent Traversal
    data = build_raw_zip([{"name": "../evil.xml", "data": b"<root/>"}])
    register("zipslip_parent.zip", data, "THREAT-01", "SEC_ZIPSLIP_PARENT", "ZipSlip relative traversal '../evil.xml'")

    # 2. ZipSlip: Absolute Unix Path
    data = build_raw_zip([{"name": "/evil.xml", "data": b"<root/>"}])
    register("zipslip_absolute.zip", data, "THREAT-02", "SEC_ZIPSLIP_ABSOLUTE", "ZipSlip absolute path '/evil.xml'")

    # 3. ZipSlip: Windows Drive Letter
    data = build_raw_zip([{"name": "C:/evil.xml", "data": b"<root/>"}])
    register("zipslip_windows_drive.zip", data, "THREAT-03", "SEC_ZIPSLIP_WINDOWS_DRIVE", "ZipSlip Windows drive 'C:/evil.xml'")

    # 4. ZipSlip: Backslash Path
    data = build_raw_zip([{"name": "folder\\..\\evil.xml", "data": b"<root/>"}])
    register("zipslip_backslash.zip", data, "THREAT-04", "SEC_ZIPSLIP_BACKSLASH", "ZipSlip backslash traversal 'folder\\..\\evil.xml'")

    # 5. Duplicate ZIP Member
    data = build_raw_zip([
        {"name": "ppt/slides/slide1.xml", "data": b"<slide1/>"},
        {"name": "ppt/slides/slide1.xml", "data": b"<slide1_duplicate/>"},
    ])
    register("duplicate_member.zip", data, "THREAT-07", "SEC_DUPLICATE_MEMBER", "Exact duplicate member name")

    # 6. ZIP Symlink Entry
    symlink_attr = (stat.S_IFLNK | 0o777) << 16
    data = build_raw_zip([{"name": "link_to_passwd", "data": b"/etc/passwd", "external_attr": symlink_attr}])
    register("symlink_entry.zip", data, "THREAT-09", "SEC_SYMLINK_MEMBER", "Unix symlink attribute entry")

    # 7. Encrypted ZIP Member
    data = build_raw_zip([{"name": "secret.xml", "data": b"<encrypted/>", "flags": 0x0001}])
    register("encrypted_member.zip", data, "THREAT-10", "SEC_ENCRYPTED_MEMBER", "Encrypted entry with bit 0 set")

    # 8. Unsupported Compression Method (Deflate64 / Method 9)
    data = build_raw_zip([{"name": "content.xml", "data": b"<data/>", "comp_method": 9}])
    register("unsupported_compression.zip", data, "THREAT-11", "SEC_UNSUPPORTED_COMPRESSION", "Unsupported compression method 9")

    # 9. Missing EOCD
    valid_base = build_raw_zip([{"name": "test.txt", "data": b"hello"}])
    data = valid_base[:-22]  # slice off EOCD
    register("missing_eocd.zip", data, "THREAT-18", "SEC_MISSING_EOCD", "Truncated archive lacking EOCD record")

    # 10. Bad Central Directory Offset
    data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], cd_offset_override=999999)
    register("bad_cd_offset.zip", data, "THREAT-19", "SEC_BAD_CD_OFFSET", "Central directory offset outside file bounds")

    # 11. Truncated Central Directory
    data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], cd_size_override=999999)
    register("truncated_central_directory.zip", data, "THREAT-19", "SEC_TRUNCATED_CD", "Central directory size exceeds archive boundary")

    # 12. Bad Local Header Offset
    data = build_raw_zip([{"name": "test.txt", "data": b"hello", "lhoff_override": 999999}])
    register("bad_local_header_offset.zip", data, "THREAT-20", "SEC_BAD_LOCAL_HEADER_OFFSET", "Local header offset points outside archive")

    # 13. Local vs Central Directory Filename Mismatch
    data = build_raw_zip([{"name": "evil.xml", "local_name_bytes": b"good.xml", "data": b"<data/>"}])
    register("local_central_filename_mismatch.zip", data, "THREAT-21", "SEC_LOCAL_CENTRAL_MISMATCH", "Local header and central directory filenames differ")

    # 14. Overlapping Member Byte Ranges
    data = build_raw_zip(
        [
            {"name": "member1.txt", "data": b"A" * 10, "csize_override": 100, "comp_method": 0},
            {"name": "member2.txt", "data": b"B" * 10, "comp_method": 0},
        ],
    )
    register("overlapping_member_ranges.zip", data, "THREAT-22", "SEC_OVERLAPPING_MEMBERS", "Two members share overlapping byte slices")

    # 15. Multi-Disk ZIP Archive
    data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], disk_num=1)
    register("multidisk_zip.zip", data, "THREAT-23", "SEC_MULTIDISK_ARCHIVE", "EOCD indicates multi-disk archive")

    # 16. ZIP64 Unsupported Policy
    data = build_raw_zip([{"name": "test.txt", "data": b"hello"}], zip64_locator=True)
    register("zip64_unsupported.zip", data, "THREAT-24", "SEC_ZIP64_UNSUPPORTED", "ZIP64 locator record present (fail-closed)")

    # 17. Truncated Compressed Deflate Stream
    data = build_raw_zip([{"name": "test.xml", "data": b"<data>" + b"X" * 1000 + b"</data>", "truncate_payload": True}])
    register("truncated_deflate_stream.zip", data, "THREAT-17", "SEC_CORRUPTED_STREAM", "Truncated deflate stream mid-decompression")

    # 18. Corrupted CRC
    data = build_raw_zip([{"name": "test.xml", "data": b"<test/>", "crc": 0xDEADBEEF}])
    register("corrupted_crc.zip", data, "THREAT-17", "SEC_CRC_MISMATCH", "Declared CRC does not match payload")

    # 19. XML DOCTYPE in DOCX
    doctype_xml = b'<?xml version="1.0"?>\n<!DOCTYPE html SYSTEM "http://127.0.0.1/evil.dtd">\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>evil</w:t></w:p></w:body></w:document>'
    data = make_minimal_docx({"word/document.xml": doctype_xml})
    register("xml_doctype.docx", data, "THREAT-28", "SEC_XML_DOCTYPE", "DOCX containing XML <!DOCTYPE> declaration")

    # 20. XML Internal Entity in DOCX
    entity_xml = b'<?xml version="1.0"?>\n<!DOCTYPE foo [<!ENTITY test "injected">]>\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>&test;</w:t></w:p></w:body></w:document>'
    data = make_minimal_docx({"word/document.xml": entity_xml})
    register("xml_internal_entity.docx", data, "THREAT-28", "SEC_XML_ENTITY", "DOCX containing internal XML ENTITY declaration")

    # 21. XML External Entity (XXE) in DOCX
    xxe_xml = b'<?xml version="1.0"?>\n<!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://127.0.0.1:9999/secret">]>\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>&xxe;</w:t></w:p></w:body></w:document>'
    data = make_minimal_docx({"word/document.xml": xxe_xml})
    register("xml_external_entity.docx", data, "THREAT-29", "SEC_XML_XXE_SYSTEM", "DOCX containing external XXE SYSTEM declaration")

    # 22. UTF-16 Encoded DOCTYPE Bypass Attempt
    utf16_text = '<?xml version="1.0" encoding="UTF-16"?>\n<!DOCTYPE doc [<!ENTITY xxe "evil">]>\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>&xxe;</w:t></w:p></w:body></w:document>'
    utf16_bytes = utf16_text.encode("utf-16-le")
    data = make_minimal_docx({"word/document.xml": utf16_bytes})
    register("xml_utf16_doctype.docx", data, "THREAT-30", "SEC_XML_DOCTYPE", "DOCX containing UTF-16-LE encoded DOCTYPE declaration")

    # 23. Malformed XML in DOCX
    malformed_xml = b'<?xml version="1.0"?>\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>unclosed tag'
    data = make_minimal_docx({"word/document.xml": malformed_xml})
    register("xml_malformed.docx", data, "THREAT-31", "SEC_XML_MALFORMED", "DOCX containing unclosed XML tags")

    # 24. Representative Cross-Format: DOCX with ZipSlip
    docx_zipslip = make_minimal_docx({"word/../outside.xml": b"<evil/>"})
    register("representative_zipslip.docx", docx_zipslip, "THREAT-01", "SEC_ZIPSLIP_PARENT", "Representative DOCX package with ZipSlip path")

    # 25. Representative Cross-Format: XLSX with Duplicate Member
    xlsx_dup = build_raw_zip([
        {"name": "[Content_Types].xml", "data": b"<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>"},
        {"name": "_rels/.rels", "data": b"<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>"},
        {"name": "xl/workbook.xml", "data": b"<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'/>"},
        {"name": "xl/worksheets/sheet1.xml", "data": b"<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'/>"},
        {"name": "xl/worksheets/sheet1.xml", "data": b"<worksheet duplicate='true'/>"},
    ])
    register("representative_duplicate.xlsx", xlsx_dup, "THREAT-07", "SEC_DUPLICATE_MEMBER", "Representative XLSX package with duplicate worksheet member")

    # 26. Representative Cross-Format: PPTX with Deep XML (Depth 150 > Limit 100)
    nested_tags = "<node>" * 150 + "deep" + "</node>" * 150
    deep_slide = f'<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">{nested_tags}</p:sld>'.encode("utf-8")
    pptx_deep = build_raw_zip([
        {"name": "[Content_Types].xml", "data": b"<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>"},
        {"name": "_rels/.rels", "data": b"<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>"},
        {"name": "ppt/presentation.xml", "data": b"<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'/>"},
        {"name": "ppt/slides/slide1.xml", "data": deep_slide},
    ])
    register("representative_deep_xml.pptx", pptx_deep, "THREAT-26", "SEC_XML_DEPTH_LIMIT", "Representative PPTX package with XML nesting depth 150")

    # Write MANIFEST.json
    manifest_path = FIXTURES_DIR / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Write README.md
    readme_path = FIXTURES_DIR / "README.md"
    readme_text = (
        "# Phase 9 Hostile Security Fixtures\n\n"
        "Deterministic synthetic fixtures for validating container and XML security preflight hardening.\n"
        f"Generated: {len(manifest)} fixtures.\n\n"
        "Run `python build_hostile_fixtures.py` to regenerate.\n"
    )
    readme_path.write_text(readme_text, encoding="utf-8")

    return manifest


if __name__ == "__main__":
    mf = generate_all_fixtures()
    print(f"Successfully generated {len(mf)} hostile security fixtures in {FIXTURES_DIR}")
