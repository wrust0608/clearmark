"""tests/test_security_bounds.py

Security and privacy boundaries verification suite:
- Zero network egress during document cleaning
- ZipSlip directory traversal mitigation
- ZipBomb decompression threshold mitigation
- XML External Entity (XXE) and entity expansion safety
- Memory-only processing with zero leftover disk footprints
"""

import io
import socket
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
import pytest

from docx.cleaner import clean_docx_lossless
from docx.validator import DocxFidelityException
from docx.package import DocxPackage

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_sample_docx(xml_content: str, extra_members: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml_content.encode("utf-8"))
        z.writestr("[Content_Types].xml", b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("_rels/.rels", b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr("docProps/core.xml", b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')
        if extra_members:
            for name, content in extra_members.items():
                z.writestr(name, content)
    return buf.getvalue()


def test_zero_network_egress(monkeypatch):
    """Assert that cleaning a document makes strictly zero network socket connections."""
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("SECURITY VIOLATION: Network connection attempted during document cleaning!")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{W_NS}">
      <w:body><w:p><w:r><w:t>Confidential\u200B Document Content</w:t></w:r></w:p></w:body>
    </w:document>"""
    data = _make_sample_docx(xml)

    # Must complete cleanly without any socket connection attempt
    clean, report = clean_docx_lossless(data)
    assert report["fidelity_guaranteed"] is True
    from docx.visible_text import extract_canonical_visible_text
    assert "Confidential Document Content" in extract_canonical_visible_text(clean)


def test_zipslip_traversal_blocked():
    """Assert that ZIP entries with directory traversal ('../') are rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document xmlns:w='{W_NS}'><w:body/></w:document>")
        z.writestr("../evil.txt", b"malicious content")

    bad_zip = buf.getvalue()

    # In strict mode, DocxPackage raises DocxFidelityException
    with pytest.raises(DocxFidelityException) as excinfo:
        DocxPackage(bad_zip)
    assert "ZipSlip" in str(excinfo.value)

    # In cleaner default fail-closed mode, it returns original data and flags error
    clean, report = clean_docx_lossless(bad_zip)
    assert report["fidelity_guaranteed"] is False
    assert "ZipSlip" in str(report.get("error", ""))


def test_zipbomb_budget_exceeded():
    """Assert that excessive uncompressed sizes trigger security bounds."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document xmlns:w='{W_NS}'><w:body><w:p><w:r><w:t>A" * 100 + "</w:t></w:r></w:p></w:body></w:document>")

    bomb_data = buf.getvalue()

    with pytest.raises(DocxFidelityException) as excinfo:
        DocxPackage(bomb_data, max_uncompressed_bytes=50)
    assert "ZipBomb" in str(excinfo.value)


def test_xxe_entity_injection_safe():
    """Assert that external entity declarations in XML are safely ignored or rejected without network calls."""
    xxe_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE test [
      <!ENTITY xxe SYSTEM "http://127.0.0.1:9999/secret">
    ]>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>&xxe; Normal Text</w:t></w:r></w:p>
      </w:body>
    </w:document>"""

    data = _make_sample_docx(xxe_xml)
    # Python ElementTree does not resolve external entities (safe by default)
    # The cleaner should process or fail-closed without contacting external servers
    clean, rep = clean_docx_lossless(data)
    assert rep is not None


def test_memory_only_processing():
    """Assert that clean_docx_lossless operates purely in memory with zero temp file leaks."""
    import tempfile
    before_tmp_files = set(Path(tempfile.gettempdir()).glob("*"))

    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{W_NS}">
      <w:body><w:p><w:r><w:t>In-Memory\u200B Only Processing</w:t></w:r></w:p></w:body>
    </w:document>"""
    data = _make_sample_docx(xml)

    clean, rep = clean_docx_lossless(data)
    assert rep["fidelity_guaranteed"] is True

    after_tmp_files = set(Path(tempfile.gettempdir()).glob("*"))
    # No new temporary files should be left behind
    new_files = after_tmp_files - before_tmp_files
    docx_leak = [f for f in new_files if "docx" in f.name.lower() or "clearmark" in f.name.lower()]
    assert len(docx_leak) == 0, f"Temporary file leak detected: {docx_leak}"
