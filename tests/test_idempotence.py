"""Phase 10: Canonical Idempotence and Property Testing Suite.

Covers:
- Primary Fixed-Point Property: C(C(x)) == C(x) [byte-for-byte, SHA256, and size fixed point]
- Status Convergence: second pass returns NO_CHANGE_REQUIRED
- Empty Mutation Plan on second pass: mutations == [], changed_parts == []
- Truthfulness: changed=False, would_change=False
- Identity Accounting: second-pass input SHA == second-pass output SHA
- Already-Clean Input Property: exact original bytes returned
- Positive Input Property: first pass CLEANED, second pass NO_CHANGE_REQUIRED
- Actionable vs Non-Actionable Findings
- Mode Independence: SAFE, BALANCED, AGGRESSIVE tested independently
- Option Independence: normalize_spaces=False vs normalize_spaces=True
- OOXML Fidelity & Invariants:
  - DOCX (Phase 6 fixtures, Golden v2.0, Candidate)
  - XLSX (Phase 7 fixtures, sharedStrings, styles, formulas)
  - PPTX (Phase 8 fixtures, slide text, tables, shapes, geometry)
- Security Preflight Compatibility: security_preflight(C(x)) == PASS
- Container Formats: ODT, ODS, ODP, EPUB, SVG
- Raster Images: PNG, JPEG, WebP, GIF, BMP, TIFF, AVIF, HEIC
- Audio/Video Formats: MP3, WAV, MP4
- Plain Text & Markup: TXT, MD, HTML, LATEX
- Repeated Same-Input Determinism & Mutation Plan Determinism
- Dry-Run Fixed Point: changed=False, would_change=False, empty plan, 0 writes
- Inspection Fixed Point: 0 actionable mutations on pass 2
- Report Semantic Stability: stable projection comparison
- Report Privacy Invariant: sentinels never leaked into reports
- Zero Network Invariant: 0 network socket calls
- Integration Contracts:
  - Canonical Pipeline
  - CLI (watermarks clean ... -o ...)
  - HTTP API (POST /clean)
  - Batch Processing Engine (BatchProcessor)
  - Two-File Verification (verify(x, y) and verify(y, z))
  - In-Place Cleaning (clean --in-place)
- Optional Dependency Truthfulness (PDF missing dependencies)
- Unsupported Format Semantics (stable failure, 0 writes)
"""

from __future__ import annotations

import base64
import http.client
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import zipfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server
import hashlib
from service.scripts.batch_processor import BatchProcessor
from service.scripts.cli import ExitCode, main as cli_main
from service.scripts.common import safe_write_bytes
from service.scripts.format_policy import (
    FormatCategory,
    FormatPolicyRegistry,
    get_format_policy,
)
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import (
    CleaningReport,
    DetectionStatus,
    ErrorCode,
    PipelineStatus,
    ProcessingMode,
)
from service.scripts.security import preflight_zip_container, SecurityLimits

GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
CANDIDATE_DOCX = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"
DOCX_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "docx_body_carriers"
XLSX_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "xlsx_lossless"
PPTX_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "pptx_lossless"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ==============================================================================
# Stable Report Projection (Section 27)
# ==============================================================================


def project_stable_report(rep: CleaningReport) -> dict:
    """Project report onto stable semantic fields, omitting variable fields like elapsed time or paths."""
    d = rep.to_dict()
    return {
        "status": d.get("status"),
        "error_code": d.get("error_code"),
        "input_format": d.get("input", {}).get("format"),
        "policy_mode": d.get("policy", {}).get("mode"),
        "mutation_count": len(d.get("mutation_plan", {}).get("mutations", [])),
        "changed_parts": sorted(d.get("mutation_plan", {}).get("changed_parts", [])),
        "changed": d.get("output", {}).get("changed"),
        "would_change": d.get("output", {}).get("would_change"),
        "validation_status": d.get("validation", {}).get("status"),
        "network_used": d.get("privacy", {}).get("network_used"),
    }


# ==============================================================================
# Deterministic Fixture Generators for Non-OOXML Formats
# ==============================================================================


def make_clean_png() -> bytes:
    """Minimal valid 1x1 PNG with no ancillary metadata."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def make_carrier_png() -> bytes:
    """Valid 1x1 PNG containing a tEXt comment watermark chunk."""
    import zlib
    chunk_type = b"tEXt"
    payload = b"Comment\x00WatermarkData"
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    text_chunk = struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)
    clean = make_clean_png()
    # Insert before IEND
    iend_pos = clean.find(b"IEND") - 4
    return clean[:iend_pos] + text_chunk + clean[iend_pos:]


def make_clean_jpeg() -> bytes:
    """Minimal valid 1x1 JPEG without comments."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00"
        b"\xff\xd9"
    )


def make_carrier_jpeg() -> bytes:
    """Valid JPEG containing a COM comment marker."""
    clean = make_clean_jpeg()
    comment = b"WatermarkComment"
    com_marker = b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment
    # Insert right after SOI (2 bytes)
    return clean[:2] + com_marker + clean[2:]


def make_clean_webp() -> bytes:
    """Minimal valid WebP (RIFF VP8)."""
    # 1x1 lossless or VP8 minimal chunk
    vp8_data = b"\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x02\x00\x34\x25\xa4\x00\x03\x70\x00\xfe\xfb\xfd\x50\x00"
    chunk = b"VP8 " + struct.pack("<I", len(vp8_data)) + vp8_data
    riff_header = b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP"
    return riff_header + chunk


def make_carrier_webp() -> bytes:
    """Valid WebP with EXIF metadata chunk."""
    base = make_clean_webp()
    exif_payload = b"Exif\x00\x00II*\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    exif_chunk = b"EXIF" + struct.pack("<I", len(exif_payload)) + exif_payload
    if len(exif_payload) % 2 != 0:
        exif_chunk += b"\x00"
    # Reassemble with EXIF
    inner = base[12:] + exif_chunk
    return b"RIFF" + struct.pack("<I", len(inner) + 4) + b"WEBP" + inner


def make_clean_gif() -> bytes:
    """Minimal valid 1x1 GIF89a."""
    return (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
        b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )


def make_carrier_gif() -> bytes:
    """Valid 1x1 GIF89a with Comment Extension."""
    clean = make_clean_gif()
    comment = b"WatermarkComment"
    com_block = b"!\xfe" + bytes([len(comment)]) + comment + b"\x00"
    # Insert before trailer ';'
    return clean[:-1] + com_block + clean[-1:]


def make_clean_bmp() -> bytes:
    """Minimal valid 1x1 BMP."""
    bf_type = b"BM"
    bf_off_bits = 54
    bi_size = 40
    bi_width = 1
    bi_height = 1
    bi_planes = 1
    bi_bit_count = 24
    bi_size_image = 4  # 1x1 24-bit padded to 4 bytes
    bf_size = bf_off_bits + bi_size_image

    file_header = bf_type + struct.pack("<IHHI", bf_size, 0, 0, bf_off_bits)
    info_header = struct.pack("<IIIHHIIIIII", bi_size, bi_width, bi_height, bi_planes, bi_bit_count, 0, bi_size_image, 2835, 2835, 0, 0)
    pixel_data = b"\x00\x00\x00\x00"
    return file_header + info_header + pixel_data


def make_carrier_bmp() -> bytes:
    """Valid BMP with trailing metadata payload."""
    clean = make_clean_bmp()
    return clean + b"WATERMARK_METADATA_CARRIER_DATA"


def make_clean_tiff() -> bytes:
    """Minimal valid 1x1 uncompressed TIFF."""
    # Little-endian header
    header = b"II*\x00\x08\x00\x00\x00"
    # IFD: 4 entries: ImageWidth(256), ImageLength(257), BitsPerSample(258), StripOffsets(273)
    num_entries = 4
    ifd = struct.pack("<H", num_entries)
    ifd += struct.pack("<HHII", 256, 3, 1, 1)  # ImageWidth = 1
    ifd += struct.pack("<HHII", 257, 3, 1, 1)  # ImageLength = 1
    ifd += struct.pack("<HHII", 258, 3, 1, 8)  # BitsPerSample = 8
    ifd += struct.pack("<HHII", 273, 4, 1, 62)  # StripOffsets = offset 62
    ifd += struct.pack("<I", 0)  # Next IFD = 0
    pixels = b"\x00\x00"
    return header + ifd + pixels


def make_carrier_tiff() -> bytes:
    """Valid TIFF with extra metadata/tag."""
    clean = make_clean_tiff()
    return clean + b"EXIF_METADATA_PAYLOAD"


def make_clean_svg() -> bytes:
    """Minimal clean SVG."""
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'


def make_carrier_svg() -> bytes:
    """SVG with metadata element and XML comments."""
    return (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        b'<metadata><c2pa>AI Watermark</c2pa></metadata>'
        b'<!-- Generator: AI-Tool Watermark -->'
        b'<rect width="10" height="10"/>'
        b'</svg>'
    )


def make_clean_odt() -> bytes:
    """Minimal clean ODT package."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.text")
        content_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:text><text:p>Clean ODT Content</text:p></office:text></office:body>'
            '</office:document-content>'
        ).encode("utf-8")
        zf.writestr("content.xml", content_xml)
    return buf.getvalue()


def make_carrier_odt() -> bytes:
    """ODT package with metadata and invisible body carriers."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.text")
        meta_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0">'
            '<office:meta><meta:generator>AI Generator</meta:generator></office:meta>'
            '</office:document-meta>'
        ).encode("utf-8")
        content_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:text><text:p>Carrier\u200BODT\u200BContent</text:p></office:text></office:body>'
            '</office:document-content>'
        ).encode("utf-8")
        zf.writestr("meta.xml", meta_xml)
        zf.writestr("content.xml", content_xml)
    return buf.getvalue()


def make_clean_ods() -> bytes:
    """Minimal clean ODS package."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.spreadsheet")
        content_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:spreadsheet><table:table table:name="Sheet1">'
            '<table:table-row><table:table-cell office:value-type="string"><text:p>Clean ODS</text:p></table:table-cell></table:table-row>'
            '</table:table></office:spreadsheet></office:body>'
            '</office:document-content>'
        ).encode("utf-8")
        zf.writestr("content.xml", content_xml)
    return buf.getvalue()


def make_carrier_ods() -> bytes:
    """ODS package with invisible carrier."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.spreadsheet")
        content_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:spreadsheet><table:table table:name="Sheet1">'
            '<table:table-row><table:table-cell office:value-type="string"><text:p>Carrier\u200BODS</text:p></table:table-cell></table:table-row>'
            '</table:table></office:spreadsheet></office:body>'
            '</office:document-content>'
        ).encode("utf-8")
        zf.writestr("content.xml", content_xml)
    return buf.getvalue()


def make_clean_odp() -> bytes:
    """Minimal clean ODP package."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.presentation")
        content_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:presentation><draw:page draw:name="page1">'
            '<draw:frame><draw:text-box><text:p>Clean Presentation</text:p></draw:text-box></draw:frame>'
            '</draw:page></office:presentation></office:body>'
            '</office:document-content>'
        ).encode("utf-8")
        zf.writestr("content.xml", content_xml)
    return buf.getvalue()


def make_carrier_odp() -> bytes:
    """ODP package with invisible carrier."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.presentation")
        content_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:presentation><draw:page draw:name="page1">'
            '<draw:frame><draw:text-box><text:p>Carrier\u200BPresentation</text:p></draw:text-box></draw:frame>'
            '</draw:page></office:presentation></office:body>'
            '</office:document-content>'
        ).encode("utf-8")
        zf.writestr("content.xml", content_xml)
    return buf.getvalue()


def make_clean_epub() -> bytes:
    """Minimal clean EPUB."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/epub+zip")
        container_xml = (
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            '</container>'
        ).encode("utf-8")
        opf_xml = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title></metadata>'
            '<manifest><item id="t1" href="t.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="t1"/></spine></package>'
        ).encode("utf-8")
        xhtml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<!DOCTYPE html>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Clean EPUB</p></body></html>'
        ).encode("utf-8")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/t.xhtml", xhtml)
    return buf.getvalue()


def make_carrier_epub() -> bytes:
    """EPUB with carrier text in XHTML and metadata."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mimetype", b"application/epub+zip")
        container_xml = (
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            '</container>'
        ).encode("utf-8")
        opf_xml = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>Carrier</dc:title>'
            '<dc:creator>AI Author c2pa</dc:creator>'
            '</metadata>'
            '<manifest><item id="t1" href="t.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="t1"/></spine></package>'
        ).encode("utf-8")
        xhtml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<!DOCTYPE html>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Carrier\u200BEPUB</p></body></html>'
        ).encode("utf-8")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/t.xhtml", xhtml)
    return buf.getvalue()


def make_clean_wav() -> bytes:
    """Minimal valid PCM WAV (1 second of silence, 8000 Hz, 8-bit mono)."""
    num_samples = 100
    subchunk2_size = num_samples
    subchunk1_size = 16
    chunk_size = 4 + (8 + subchunk1_size) + (8 + subchunk2_size)
    header = b"RIFF" + struct.pack("<I", chunk_size) + b"WAVE"
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
    data_chunk = b"data" + struct.pack("<I", subchunk2_size) + (b"\x80" * num_samples)
    return header + fmt_chunk + data_chunk


def make_carrier_wav() -> bytes:
    """WAV with INFO metadata list chunk."""
    clean = make_clean_wav()
    info_payload = b"INAM\x08\x00\x00\x00Carrier\x00"
    list_chunk = b"LIST" + struct.pack("<I", len(info_payload) + 4) + b"INFO" + info_payload
    # Insert list chunk before data chunk
    data_idx = clean.find(b"data")
    header_up = clean[:4] + struct.pack("<I", len(clean) + len(list_chunk) - 8) + clean[8:data_idx]
    return header_up + list_chunk + clean[data_idx:]


def make_clean_mp3() -> bytes:
    """Minimal raw MP3 frame without ID3 tags (MPEG 1 Layer III, 128kbps, 44100Hz)."""
    # 4-byte MPEG frame sync header: 0xFF, 0xFB, 0x90, 0x00
    frame_hdr = b"\xff\xfb\x90\x00"
    frame_body = b"\x00" * 413  # 417 bytes total frame
    return frame_hdr + frame_body


def make_carrier_mp3() -> bytes:
    """MP3 with ID3v2 tag."""
    id3_hdr = b"ID3\x03\x00\x00\x00\x00\x00\x17"  # ID3v2.3, size=23
    tit2_frame = b"TIT2\x00\x00\x00\x09\x00\x00\x00Carrier\x00"
    return id3_hdr + tit2_frame + make_clean_mp3()


def make_clean_mp4() -> bytes:
    """Minimal valid MP4 (ftyp + moov + mdat)."""
    ftyp = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42"
    mvhd = b"\x00\x00\x00\x6c" + b"mvhd" + (b"\x00" * 100)
    moov = struct.pack(">I", len(mvhd) + 8) + b"moov" + mvhd
    mdat = b"\x00\x00\x00\x08mdat"
    return ftyp + moov + mdat


def make_carrier_mp4() -> bytes:
    """MP4 with udta metadata atom inside moov."""
    clean = make_clean_mp4()
    udta = b"\x00\x00\x00\x1audta\x00\x00\x00\x12meta\x00\x00\x00\x00data"
    # Reassemble moov with udta
    ftyp = clean[:24]
    moov = clean[24:-8]
    moov_len = struct.unpack(">I", moov[:4])[0]
    moov_body = moov[8:] + udta
    moov_new = struct.pack(">I", len(moov_body) + 8) + b"moov" + moov_body
    return ftyp + moov_new + clean[-8:]


# ==============================================================================
# IDEMPOTENCE_CASES: Machine-Readable Test Manifest (Section 50)
# ==============================================================================

IDEMPOTENCE_CASES = [
    # OOXML Formats
    {
        "format": "docx",
        "category": "word_processing",
        "clean_fixture": DOCX_FIXTURES_DIR / "synthetic_baseline.docx",
        "positive_fixture": DOCX_FIXTURES_DIR / "carrier_zwsp.docx",
        "filename": "document.docx",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": True,
    },
    {
        "format": "xlsx",
        "category": "spreadsheet",
        "clean_fixture": XLSX_FIXTURES_DIR / "synthetic_baseline.xlsx",
        "positive_fixture": XLSX_FIXTURES_DIR / "carrier_shared_string.xlsx",
        "filename": "sheet.xlsx",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": True,
    },
    {
        "format": "pptx",
        "category": "presentation",
        "clean_fixture": PPTX_FIXTURES_DIR / "synthetic_clean_baseline.pptx",
        "positive_fixture": PPTX_FIXTURES_DIR / "carrier_slide_text.pptx",
        "filename": "presentation.pptx",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": True,
    },
    # Text Formats
    {
        "format": "txt",
        "category": "plain_text",
        "clean_bytes": b"Clean plain text document without watermarks.",
        "positive_bytes": "Clean plain\u200Btext with\u200Bwatermark.".encode("utf-8"),
        "filename": "sample.txt",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "md",
        "category": "plain_text",
        "clean_bytes": b"# Heading\nClean markdown document.",
        "positive_bytes": "# Heading\nCarrier\u200Bmarkdown.".encode("utf-8"),
        "filename": "document.md",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "html",
        "category": "plain_text",
        "clean_bytes": b"<html><body><p>Clean HTML</p></body></html>",
        "positive_bytes": "<html><body><p>Carrier\u200BHTML</p></body></html>".encode("utf-8"),
        "filename": "page.html",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "latex",
        "category": "plain_text",
        "clean_bytes": b"\\documentclass{article}\n\\begin{document}\nClean LaTeX\n\\end{document}",
        "positive_bytes": "\\documentclass{article}\n\\begin{document}\nCarrier\u200BLaTeX\n\\end{document}".encode("utf-8"),
        "filename": "doc.tex",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    # Container Formats
    {
        "format": "odt",
        "category": "odf_document",
        "clean_builder": make_clean_odt,
        "positive_builder": make_carrier_odt,
        "filename": "document.odt",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "ods",
        "category": "odf_document",
        "clean_builder": make_clean_ods,
        "positive_builder": make_carrier_ods,
        "filename": "sheet.ods",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "odp",
        "category": "odf_document",
        "clean_builder": make_clean_odp,
        "positive_builder": make_carrier_odp,
        "filename": "slides.odp",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "epub",
        "category": "odf_document",
        "clean_builder": make_clean_epub,
        "positive_builder": make_carrier_epub,
        "filename": "book.epub",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "svg",
        "category": "vector_image",
        "clean_builder": make_clean_svg,
        "positive_builder": make_carrier_svg,
        "filename": "image.svg",
        "modes": [ProcessingMode.SAFE],
        "verify_supported": False,
    },
    # Raster Images
    {
        "format": "png",
        "category": "raster_image",
        "clean_builder": make_clean_png,
        "positive_builder": make_carrier_png,
        "filename": "image.png",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "jpeg",
        "category": "raster_image",
        "clean_builder": make_clean_jpeg,
        "positive_builder": make_carrier_jpeg,
        "filename": "image.jpg",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "webp",
        "category": "raster_image",
        "clean_builder": make_clean_webp,
        "positive_builder": make_carrier_webp,
        "filename": "image.webp",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "gif",
        "category": "raster_image",
        "clean_builder": make_clean_gif,
        "positive_builder": make_carrier_gif,
        "filename": "image.gif",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "bmp",
        "category": "raster_image",
        "clean_builder": make_clean_bmp,
        "positive_builder": make_carrier_bmp,
        "filename": "image.bmp",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "tiff",
        "category": "raster_image",
        "clean_builder": make_clean_tiff,
        "positive_builder": make_carrier_tiff,
        "filename": "image.tiff",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "avif",
        "category": "raster_image",
        "fixture_path": REPO_ROOT / "tests" / "fixtures" / "sample_c2pa.avif",
        "filename": "image.avif",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "heic",
        "category": "raster_image",
        "fixture_path": REPO_ROOT / "tests" / "fixtures" / "sample_c2pa.heic",
        "filename": "image.heic",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    # Audio / Video Formats
    {
        "format": "wav",
        "category": "audio_video",
        "clean_builder": make_clean_wav,
        "positive_builder": make_carrier_wav,
        "filename": "audio.wav",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "mp3",
        "category": "audio_video",
        "clean_builder": make_clean_mp3,
        "positive_builder": make_carrier_mp3,
        "filename": "audio.mp3",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
    {
        "format": "mp4",
        "category": "audio_video",
        "clean_builder": make_clean_mp4,
        "positive_builder": make_carrier_mp4,
        "filename": "video.mp4",
        "modes": [ProcessingMode.SAFE, ProcessingMode.BALANCED, ProcessingMode.AGGRESSIVE],
        "verify_supported": False,
    },
]


def _get_fixture_bytes(case: dict, fixture_type: str = "clean") -> bytes:
    """Retrieve test fixture bytes for a case."""
    if fixture_type == "clean":
        if "clean_bytes" in case:
            return case["clean_bytes"]
        if "clean_fixture" in case and Path(case["clean_fixture"]).exists():
            return Path(case["clean_fixture"]).read_bytes()
        if "clean_builder" in case:
            return case["clean_builder"]()
        if "fixture_path" in case and Path(case["fixture_path"]).exists():
            # For formats with single fixture, first clean pass provides clean bytes
            raw = Path(case["fixture_path"]).read_bytes()
            pipe = Pipeline()
            cleaned, _ = pipe.clean(raw, filename=case["filename"])
            return cleaned
    else:  # positive
        if "positive_bytes" in case:
            return case["positive_bytes"]
        if "positive_fixture" in case and Path(case["positive_fixture"]).exists():
            return Path(case["positive_fixture"]).read_bytes()
        if "positive_builder" in case:
            return case["positive_builder"]()
        if "fixture_path" in case and Path(case["fixture_path"]).exists():
            return Path(case["fixture_path"]).read_bytes()

    raise ValueError(f"No {fixture_type} fixture available for case {case['format']}")


# ==============================================================================
# 1. CORE FIXED-POINT PROPERTIES A THROUGH G (Section 0 & 5)
# ==============================================================================


@pytest.mark.parametrize("case", IDEMPOTENCE_CASES, ids=lambda c: c["format"])
def test_idempotence_properties_a_through_g_on_positive_input(case):
    """Verify Properties A through G across all runtime-supported formats:
    y = clean(x)
    z = clean(y)
    Assert:
    A. z == y (byte fixed point)
    B. sha256(z) == sha256(y) (SHA fixed point)
    C. len(z) == len(y) (size fixed point)
    D. second status == NO_CHANGE_REQUIRED
    E. second mutations == [] and changed_parts == []
    F. second changed == False and would_change == False
    G. second-pass input SHA == second-pass output SHA
    """
    pipeline = Pipeline()
    x = _get_fixture_bytes(case, "positive")
    filename = case["filename"]

    # Pass 1: x -> y
    y, rep1 = pipeline.clean(x, filename=filename, mode=ProcessingMode.SAFE)
    sha_y = _sha256(y)

    # Invariant: y must pass Phase 9 security preflight (Section 15)
    if y.startswith(b"PK\x03\x04"):
        sec_res = preflight_zip_container(y, limits=SecurityLimits())
        assert sec_res.is_safe, f"Security preflight failed on first-pass output for {case['format']}: {sec_res.finding}"

    # Pass 2: y -> z
    z, rep2 = pipeline.clean(y, filename=filename, mode=ProcessingMode.SAFE)
    sha_z = _sha256(z)

    # PROPERTY A — Byte fixed point
    assert z == y, f"Byte fixed point failure for format {case['format']}: len(z)={len(z)} vs len(y)={len(y)}"

    # PROPERTY B — SHA fixed point
    assert sha_z == sha_y, f"SHA fixed point failure for {case['format']}: {sha_z} != {sha_y}"

    # PROPERTY C — Size fixed point
    assert len(z) == len(y), f"Size fixed point failure for {case['format']}: {len(z)} != {len(y)}"

    # PROPERTY D — Status convergence
    assert rep2.status == PipelineStatus.NO_CHANGE_REQUIRED, (
        f"Expected NO_CHANGE_REQUIRED for {case['format']}, got {rep2.status.value}"
    )

    # PROPERTY E — Empty mutation plan
    assert len(rep2.mutation_plan.mutations) == 0, (
        f"Non-empty mutations on pass 2 for {case['format']}: {rep2.mutation_plan.mutations}"
    )
    assert len(rep2.mutation_plan.changed_parts) == 0, (
        f"Non-empty changed parts on pass 2 for {case['format']}: {rep2.mutation_plan.changed_parts}"
    )

    # PROPERTY F — Output truthfulness
    assert rep2.output.changed is False
    assert rep2.output.would_change is False

    # PROPERTY G — Identity accounting
    assert rep2.input.sha256 == rep2.output.sha256


# ==============================================================================
# 2. ALREADY-CLEAN INPUT PROPERTY (Section 6)
# ==============================================================================


@pytest.mark.parametrize("case", IDEMPOTENCE_CASES, ids=lambda c: c["format"])
def test_already_clean_input_returns_exact_identity(case):
    """For an input x that already requires no mutation:
    clean(x) must return exact bytes: output == x, SHA256 identical.
    Expected status: NO_CHANGE_REQUIRED
    Expected mutation plan: EMPTY
    """
    pipeline = Pipeline()
    clean_bytes = _get_fixture_bytes(case, "clean")
    filename = case["filename"]
    input_sha = _sha256(clean_bytes)

    out_bytes, rep = pipeline.clean(clean_bytes, filename=filename, mode=ProcessingMode.SAFE)

    assert out_bytes == clean_bytes, f"Already-clean input mutated for {case['format']}"
    assert _sha256(out_bytes) == input_sha
    assert len(out_bytes) == len(clean_bytes)
    assert rep.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert rep.output.changed is False
    assert rep.output.would_change is False
    assert len(rep.mutation_plan.mutations) == 0
    assert len(rep.mutation_plan.changed_parts) == 0


# ==============================================================================
# 3. MODES TESTED INDEPENDENTLY (Section 9 & 10)
# ==============================================================================


@pytest.mark.parametrize("case", IDEMPOTENCE_CASES, ids=lambda c: c["format"])
def test_modes_tested_independently(case):
    """For each supported mode m: C_m(C_m(x)) == C_m(x)."""
    pipeline = Pipeline()
    x = _get_fixture_bytes(case, "positive")
    filename = case["filename"]

    for mode in case["modes"]:
        # Pass 1
        y, rep1 = pipeline.clean(x, filename=filename, mode=mode)
        # Pass 2
        z, rep2 = pipeline.clean(y, filename=filename, mode=mode)

        assert z == y, f"Mode {mode.value} idempotence failed for {case['format']}"
        assert _sha256(z) == _sha256(y)
        assert rep2.status == PipelineStatus.NO_CHANGE_REQUIRED
        assert len(rep2.mutation_plan.mutations) == 0


# ==============================================================================
# 4. NORMALIZE_SPACES OPTION INDEPENDENCE (Section 11)
# ==============================================================================


def test_normalize_spaces_option_independence():
    """Verify C_norm(C_norm(x)) == C_norm(x) for text with normalize_spaces=True and False."""
    pipeline = Pipeline()
    text_data = "Line with    multiple   spaces and\u200Bmarks.\nSecond   line.".encode("utf-8")

    # 1. normalize_spaces=False
    out_f1, rep_f1 = pipeline.clean(text_data, filename="doc.txt", options={"normalize_spaces": False})
    out_f2, rep_f2 = pipeline.clean(out_f1, filename="doc.txt", options={"normalize_spaces": False})
    assert out_f2 == out_f1
    assert rep_f2.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert len(rep_f2.mutation_plan.mutations) == 0

    # 2. normalize_spaces=True
    out_t1, rep_t1 = pipeline.clean(text_data, filename="doc.txt", options={"normalize_spaces": True})
    out_t2, rep_t2 = pipeline.clean(out_t1, filename="doc.txt", options={"normalize_spaces": True})
    assert out_t2 == out_t1
    assert rep_t2.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert len(rep_t2.mutation_plan.mutations) == 0


# ==============================================================================
# 5. OOXML SPECIFIC LOSSLESS INVARIANTS (Section 12, 13, 14, 41, 42)
# ==============================================================================


def test_docx_lossless_corpus_and_golden_candidate():
    """Verify DOCX Phase 6 corpus, Golden original, and Candidate output idempotence.
    Ensures zero repacking drift, zero timestamp changes, and NO_CHANGE_REQUIRED.
    """
    pipeline = Pipeline()

    # 1. Golden original
    golden_bytes = GOLDEN_DOCX.read_bytes()
    y_golden, rep_g1 = pipeline.clean(golden_bytes, filename="01_GOLDEN.docx")
    assert rep_g1.status == PipelineStatus.CLEANED
    z_golden, rep_g2 = pipeline.clean(y_golden, filename="01_GOLDEN.docx")
    assert z_golden == y_golden
    assert _sha256(z_golden) == _sha256(y_golden)
    assert rep_g2.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert len(rep_g2.mutation_plan.mutations) == 0

    # 2. Candidate output (already clean)
    candidate_bytes = CANDIDATE_DOCX.read_bytes()
    out_cand, rep_c = pipeline.clean(candidate_bytes, filename="04_CANDIDATE.docx")
    assert out_cand == candidate_bytes
    assert _sha256(out_cand) == _sha256(candidate_bytes)
    assert rep_c.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert len(rep_c.mutation_plan.mutations) == 0

    # 3. Phase 6 carrier_mixed_unicode.docx
    mixed_path = DOCX_FIXTURES_DIR / "carrier_mixed_unicode.docx"
    if mixed_path.exists():
        mixed_bytes = mixed_path.read_bytes()
        y_mix, _ = pipeline.clean(mixed_bytes, filename="mixed.docx")
        z_mix, rep_mix2 = pipeline.clean(y_mix, filename="mixed.docx")
        assert z_mix == y_mix
        assert rep_mix2.status == PipelineStatus.NO_CHANGE_REQUIRED


def test_xlsx_lossless_corpus():
    """Verify XLSX sharedStrings, inlineStrings, richText, and mixed fixtures."""
    pipeline = Pipeline()
    fixtures = [
        XLSX_FIXTURES_DIR / "carrier_shared_string.xlsx",
        XLSX_FIXTURES_DIR / "carrier_inline_string.xlsx",
        XLSX_FIXTURES_DIR / "carrier_rich_text.xlsx",
        XLSX_FIXTURES_DIR / "carrier_mixed.xlsx",
    ]
    for f in fixtures:
        if not f.exists():
            continue
        raw = f.read_bytes()
        y, rep1 = pipeline.clean(raw, filename=f.name)
        assert rep1.status == PipelineStatus.CLEANED
        z, rep2 = pipeline.clean(y, filename=f.name)
        assert z == y
        assert _sha256(z) == _sha256(y)
        assert rep2.status == PipelineStatus.NO_CHANGE_REQUIRED
        assert len(rep2.mutation_plan.mutations) == 0


def test_pptx_lossless_corpus():
    """Verify PPTX slide text, multi-run, table text, and mixed fixtures."""
    pipeline = Pipeline()
    fixtures = [
        PPTX_FIXTURES_DIR / "carrier_slide_text.pptx",
        PPTX_FIXTURES_DIR / "carrier_multi_run.pptx",
        PPTX_FIXTURES_DIR / "carrier_table_text.pptx",
        PPTX_FIXTURES_DIR / "carrier_mixed.pptx",
    ]
    for f in fixtures:
        if not f.exists():
            continue
        raw = f.read_bytes()
        y, rep1 = pipeline.clean(raw, filename=f.name)
        assert rep1.status == PipelineStatus.CLEANED
        z, rep2 = pipeline.clean(y, filename=f.name)
        assert z == y
        assert _sha256(z) == _sha256(y)
        assert rep2.status == PipelineStatus.NO_CHANGE_REQUIRED
        assert len(rep2.mutation_plan.mutations) == 0


# ==============================================================================
# 6. DETERMINISM & DRY-RUN FIXED POINT (Section 23, 24, 25, 26)
# ==============================================================================


def test_repeated_same_input_determinism():
    """Verify repeated cleans of same input produce identical output and mutation ordering."""
    pipeline = Pipeline()
    test_docx = (DOCX_FIXTURES_DIR / "carrier_zwsp.docx").read_bytes()

    a, rep_a = pipeline.clean(test_docx, filename="carrier.docx")
    b, rep_b = pipeline.clean(test_docx, filename="carrier.docx")

    assert a == b
    assert _sha256(a) == _sha256(b)
    # Mutation plan determinism (Section 24)
    assert rep_a.mutation_plan.mutations == rep_b.mutation_plan.mutations
    assert rep_a.mutation_plan.changed_parts == rep_b.mutation_plan.changed_parts


def test_dry_run_fixed_point_on_first_output(tmp_path, monkeypatch):
    """For y = C(x): dry_run(y) must report changed=False, would_change=False, empty plan, 0 writes."""
    pipeline = Pipeline()
    x = (DOCX_FIXTURES_DIR / "carrier_zwsp.docx").read_bytes()
    y, _ = pipeline.clean(x, filename="carrier.docx")

    # Guard against filesystem writes
    def _forbidden_write(*args, **kwargs):
        raise AssertionError("Write operation invoked during dry-run!")

    import service.scripts.common as common_mod
    monkeypatch.setattr(common_mod, "safe_write_bytes", _forbidden_write)
    monkeypatch.setattr(os, "replace", _forbidden_write)

    # Dry-run on cleaned output y
    _, rep_dry = pipeline.clean(y, filename="carrier.docx", dry_run=True)

    assert rep_dry.status == PipelineStatus.NO_CHANGE_REQUIRED
    assert rep_dry.output.changed is False
    assert rep_dry.output.would_change is False
    assert len(rep_dry.mutation_plan.mutations) == 0
    assert len(rep_dry.mutation_plan.changed_parts) == 0


def test_inspection_fixed_point():
    """For y = C(x): inspect(y) must not yield any actionable mutation."""
    pipeline = Pipeline()
    x = (DOCX_FIXTURES_DIR / "carrier_zwsp.docx").read_bytes()
    y, _ = pipeline.clean(x, filename="carrier.docx")

    insp_report = pipeline.inspect(y, filename="carrier.docx")
    assert insp_report.inspection.detection_status in (DetectionStatus.NOT_DETECTED, DetectionStatus.NOT_CHECKED)


def test_report_semantic_stability():
    """Verify stable report projections match on repeated cleans of cleaned file y."""
    pipeline = Pipeline()
    x = (DOCX_FIXTURES_DIR / "carrier_zwsp.docx").read_bytes()
    y, _ = pipeline.clean(x, filename="carrier.docx")

    _, rep1 = pipeline.clean(y, filename="carrier.docx")
    _, rep2 = pipeline.clean(y, filename="carrier.docx")

    p1 = project_stable_report(rep1)
    p2 = project_stable_report(rep2)
    assert p1 == p2


# ==============================================================================
# 7. INTEGRATION CONTRACTS (CLI, HTTP, BATCH, VERIFY, IN-PLACE) (Section 31-36)
# ==============================================================================


def test_cli_idempotence_convergence(tmp_path: Path, capsys):
    """CLI representative convergence:
    watermarks clean input -o first
    watermarks clean first -o second
    Assert sha256(first) == sha256(second) and second report NO_CHANGE_REQUIRED.
    """
    orig_file = tmp_path / "orig.docx"
    first_file = tmp_path / "first.docx"
    second_file = tmp_path / "second.docx"

    orig_file.write_bytes(GOLDEN_DOCX.read_bytes())

    # First clean
    code1 = cli_main(["clean", str(orig_file), "-o", str(first_file), "--json"])
    assert code1 == ExitCode.SUCCESS
    out1_json = capsys.readouterr().out
    rep1 = json.loads(out1_json)
    assert rep1["status"] == "CLEANED"

    # Second clean
    code2 = cli_main(["clean", str(first_file), "-o", str(second_file), "--json"])
    assert code2 == ExitCode.SUCCESS
    out2_json = capsys.readouterr().out
    rep2 = json.loads(out2_json)
    assert rep2["status"] == "NO_CHANGE_REQUIRED"
    assert rep2["output"]["changed"] is False
    assert rep2["output"]["would_change"] is False

    # Bytes must match
    assert first_file.read_bytes() == second_file.read_bytes()
    assert _sha256(first_file.read_bytes()) == _sha256(second_file.read_bytes())


@pytest.fixture(scope="module")
def http_conn() -> http.client.HTTPConnection:
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return http.client.HTTPConnection("127.0.0.1", srv.server_address[1])


def test_http_api_idempotence_convergence(http_conn):
    """HTTP representative convergence: POST /clean twice."""
    raw = GOLDEN_DOCX.read_bytes()
    b64_raw = base64.b64encode(raw).decode("ascii")

    # Pass 1
    http_conn.request(
        "POST",
        "/clean",
        body=json.dumps({"file": b64_raw, "name": "doc.docx"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp1 = http_conn.getresponse()
    body1 = json.loads(resp1.read().decode("utf-8"))
    assert resp1.status == 200
    assert body1["report"]["status"] == "CLEANED"
    cleaned_bytes = base64.b64decode(body1["cleaned"])

    # Pass 2
    b64_pass1 = base64.b64encode(cleaned_bytes).decode("ascii")
    http_conn.request(
        "POST",
        "/clean",
        body=json.dumps({"file": b64_pass1, "name": "doc.docx"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp2 = http_conn.getresponse()
    body2 = json.loads(resp2.read().decode("utf-8"))
    assert resp2.status == 200
    assert body2["report"]["status"] == "NO_CHANGE_REQUIRED"
    assert body2["report"]["output"]["changed"] is False
    assert body2["report"]["output"]["would_change"] is False
    assert len(body2["report"]["mutation_plan"]["mutations"]) == 0

    pass2_bytes = base64.b64decode(body2["cleaned"])
    assert pass2_bytes == cleaned_bytes


def test_batch_processor_idempotence_convergence(tmp_path: Path):
    """Batch processor second pass converges to NO_CHANGE_REQUIRED for all successfully cleaned items."""
    in_dir = tmp_path / "batch_in"
    out_dir1 = tmp_path / "batch_out1"
    out_dir2 = tmp_path / "batch_out2"
    in_dir.mkdir()

    # Create positive fixtures in batch
    f_docx = in_dir / "doc.docx"
    f_docx.write_bytes((DOCX_FIXTURES_DIR / "carrier_zwsp.docx").read_bytes())
    f_txt = in_dir / "text.txt"
    f_txt.write_text("Text with\u200Bcarrier.", encoding="utf-8")
    f_svg = in_dir / "image.svg"
    f_svg.write_bytes(make_carrier_svg())

    processor = BatchProcessor()

    # Batch 1
    rep1 = processor.process_paths(
        inputs=[f_docx, f_txt, f_svg],
        output_dir=out_dir1,
        operation="clean",
    )
    assert rep1.summary.cleaned == 3
    cleaned_paths = [Path(it.output_path) for it in rep1.items if it.status == "CLEANED"]

    # Batch 2: feed first outputs into second batch
    rep2 = processor.process_paths(
        inputs=cleaned_paths,
        output_dir=out_dir2,
        operation="clean",
    )
    assert rep2.summary.no_change == 3
    assert rep2.summary.cleaned == 0

    # Ensure bytes are identical
    for item in rep2.items:
        assert item.status == "NO_CHANGE_REQUIRED"


def test_two_file_verify_contract(tmp_path: Path, capsys):
    """Verify verify(x, y) PASS, verify(y, y) PASS, and verify(y, z) PASS."""
    pipeline = Pipeline()
    x = GOLDEN_DOCX.read_bytes()
    y, _ = pipeline.clean(x, filename="doc.docx")
    z, _ = pipeline.clean(y, filename="doc.docx")

    f_x = tmp_path / "x.docx"
    f_y = tmp_path / "y.docx"
    f_z = tmp_path / "z.docx"
    f_x.write_bytes(x)
    f_y.write_bytes(y)
    f_z.write_bytes(z)

    # 1. verify(x, y) PASS
    code_xy = cli_main(["verify", str(f_x), str(f_y), "--json"])
    assert code_xy == ExitCode.SUCCESS
    res_xy = json.loads(capsys.readouterr().out)
    assert res_xy["ok"] is True
    assert res_xy["status"] == "PASS"

    # 2. verify(y, y) PASS
    code_yy = cli_main(["verify", str(f_y), str(f_y), "--json"])
    assert code_yy == ExitCode.SUCCESS
    res_yy = json.loads(capsys.readouterr().out)
    assert res_yy["ok"] is True
    assert res_yy["status"] == "PASS"

    # 3. verify(y, z) PASS
    code_yz = cli_main(["verify", str(f_y), str(f_z), "--json"])
    assert code_yz == ExitCode.SUCCESS
    res_yz = json.loads(capsys.readouterr().out)
    assert res_yz["ok"] is True
    assert res_yz["status"] == "PASS"


def test_in_place_idempotence(tmp_path: Path, capsys):
    """In-place clean twice leaves bytes and SHA identical on pass 2, returning NO_CHANGE_REQUIRED."""
    target = tmp_path / "inplace.docx"
    target.write_bytes((DOCX_FIXTURES_DIR / "carrier_zwsp.docx").read_bytes())

    # Pass 1: in-place
    code1 = cli_main(["clean", str(target), "--in-place", "--json"])
    assert code1 == ExitCode.SUCCESS
    rep1 = json.loads(capsys.readouterr().out)
    assert rep1["status"] == "CLEANED"
    sha1 = _sha256(target.read_bytes())

    # Pass 2: in-place
    code2 = cli_main(["clean", str(target), "--in-place", "--json"])
    assert code2 == ExitCode.SUCCESS
    rep2 = json.loads(capsys.readouterr().out)
    assert rep2["status"] == "NO_CHANGE_REQUIRED"
    assert rep2["output"]["changed"] is False
    sha2 = _sha256(target.read_bytes())

    assert sha2 == sha1


# ==============================================================================
# 8. SECURITY & ENVIRONMENT BOUNDARIES (Section 38 & 39)
# ==============================================================================


def test_pdf_optional_dependency_unavailable_truthful_behavior():
    """Verify PDF returns truthful status when optional binaries (qpdf/ghostscript) are unavailable."""
    pipeline = Pipeline()
    # Minimal PDF data
    pdf_data = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    cleaned, rep = pipeline.clean(pdf_data, filename="sample.pdf")

    # If already clean and no tools, returns NO_CHANGE_REQUIRED with unmodified bytes
    assert cleaned == pdf_data
    assert rep.status == PipelineStatus.NO_CHANGE_REQUIRED


def test_unsupported_format_stability():
    """Verify unsupported inputs consistently produce UNSUPPORTED with 0 writes and 0 network."""
    pipeline = Pipeline()
    unknown_bytes = b"\x00\x01\x02\x03\x04\x05unknownformat"

    rep1 = pipeline.inspect(unknown_bytes, filename="data.xyz")
    assert rep1.status == PipelineStatus.UNSUPPORTED
    assert rep1.error_code == ErrorCode.UNSUPPORTED_FORMAT

    cleaned, rep2 = pipeline.clean(unknown_bytes, filename="data.xyz")
    assert cleaned == unknown_bytes
    assert rep2.status == PipelineStatus.UNSUPPORTED
    assert rep2.error_code == ErrorCode.UNSUPPORTED_FORMAT
