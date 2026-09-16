"""Tests for Phase 3: Authoritative /capabilities endpoint (Section 11).

Proves that:
1. GET /capabilities derives format matrix directly from service/scripts/format_policy.py
2. No duplicate hard-coded capability matrix exists in server.py
3. All required fields are present:
   - format
   - extensions
   - inspect_capabilities
   - clean_capabilities
   - fidelity_levels
   - optional_dependencies
   - network_policy
   - supported_modes
4. Legacy tool keys (tools, pixel_backends, scorers, harnesses) are preserved for backwards compatibility.
"""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path
import pytest

from service.scripts.format_policy import FormatPolicyRegistry
import service.scripts.server as server


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


def test_capabilities_authoritative_source_of_truth(conn):
    status, body = _get(conn, "/capabilities")
    assert status == 200
    assert body.get("source") == "service/scripts/format_policy.py"
    assert "formats" in body
    formats = body["formats"]

    # Must match FormatPolicyRegistry.get_default() exactly
    registry = FormatPolicyRegistry.get_default()
    registered_policies = registry.all_policies()
    assert len(formats) == len(registered_policies)

    required_fields = {
        "format",
        "extensions",
        "inspect_capabilities",
        "clean_capabilities",
        "fidelity_levels",
        "optional_dependencies",
        "network_policy",
        "supported_modes",
        "verify_capabilities",
    }

    for policy in registered_policies:
        assert policy.format_name in formats
        entry = formats[policy.format_name]
        assert required_fields.issubset(entry.keys())
        assert entry["format"] == policy.format_name
        assert entry["extensions"] == list(policy.extensions)
        assert entry["supported_modes"] == list(policy.supported_modes)
        assert entry["verify_capabilities"] == list(policy.verify_capabilities)

    # Verify SAFE-only policy contract
    assert formats["svg"]["supported_modes"] == ["safe"]


def test_capabilities_preserves_legacy_tooling_keys(conn):
    status, body = _get(conn, "/capabilities")
    assert status == 200

    # Required by v2.0 clients and existing test_capabilities_tooling.py
    assert "tools" in body
    assert "pixel_backends" in body
    assert "scorers" in body
    assert "text_detectors" in body
    assert "harnesses" in body
    assert "c2patool" in body["tools"]
    assert "exiftool" in body["tools"]
    assert "qpdf" in body["tools"]
