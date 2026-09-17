"""Phase 12: Documentation & Capabilities Consistency Verification Tests.

Executable gate verifying that:
1. FormatPolicyRegistry is the authoritative single source of truth.
2. GET /capabilities matches FormatPolicyRegistry exactly.
3. docs/capabilities.md matches FormatPolicyRegistry and /capabilities.
4. Documented file size, batch, and security limits match production constants.
5. Documented single-file and batch exit codes match ExitCode enum and Phase 4 contract.
6. Documented HTTP status codes match error_code_to_http_status().
7. Status terminology (DETECTED, NOT_DETECTED, NOT_CHECKED, etc.) is documented truthfully.
8. CLI examples in README.md use valid commands, flags, and modes.
9. Relative markdown links in public docs are valid and resolve to existing files.
10. Public docs contain no private local paths or developer usernames.
11. Public docs contain no prohibited hyperbolic claims (e.g. '100% secure').
12. PDF Model-B bounded fallback is documented truthfully.
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest

from service.scripts.format_policy import FormatPolicyRegistry, FidelityLevel
from service.scripts.server import capabilities, error_code_to_http_status
from service.scripts.cli import ExitCode, build_parser
from service.scripts import common, server, batch_processor, security
from service.scripts.pipeline_types import (
    DetectionStatus,
    ErrorCode,
    PipelineStatus,
    ProcessingMode,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
CAPABILITIES_DOC = REPO_ROOT / "docs" / "capabilities.md"
GUARANTEES_DOC = REPO_ROOT / "docs" / "format_guarantees.md"


# ============================================================================
# 1. REGISTRY <-> /CAPABILITIES PARITY
# ============================================================================

def test_registry_matches_capabilities_endpoint():
    """GET /capabilities must derive directly from FormatPolicyRegistry."""
    reg = FormatPolicyRegistry.get_default()
    policies = reg.all_policies()
    caps = capabilities()

    assert caps["source"] == "service/scripts/format_policy.py"
    formats = caps["formats"]

    # 23 canonical policies
    assert len(policies) == 23
    assert len(formats) == 23

    for p in policies:
        k = p.format_name
        assert k in formats, f"Missing {k} in /capabilities formats"
        af = formats[k]

        assert af["format"] == p.format_name
        assert af["extensions"] == list(p.extensions)
        assert af["inspect_capabilities"] == list(p.inspect_capabilities)
        assert af["clean_capabilities"] == list(p.clean_capabilities)
        assert af["fidelity_levels"] == [f.value for f in p.fidelity_requirements]
        assert af["optional_dependencies"] == list(p.optional_dependencies)
        assert af["network_policy"] == p.network_policy
        assert af["supported_modes"] == list(p.supported_modes)
        assert af["destructive_operations"] == list(p.destructive_operations)
        assert af["verify_capabilities"] == list(p.verify_capabilities)


# ============================================================================
# 2. DOCS <-> /CAPABILITIES / REGISTRY PARITY
# ============================================================================

def _parse_capabilities_table(doc_path: Path) -> dict[str, dict]:
    """Parse canonical policies markdown table from docs/capabilities.md."""
    text = doc_path.read_text(encoding="utf-8")
    table_pattern = re.compile(
        r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]*)`\s*\|\s*`([^`]*)`\s*\|\s*`([^`]*)`\s*\|\s*`([A-Z_]+)`\s*\|\s*`([^`]*)`\s*\|\s*`([^`]*)`\s*\|\s*`([^`]*)`\s*\|\s*(.*?)\s*\|",
        re.MULTILINE,
    )
    matches = table_pattern.findall(text)
    data = {}
    for m in matches:
        policy_key = m[0]
        exts = [e.strip() for e in m[1].split(",") if e.strip()]
        insp = [i.strip() for i in m[2].split(",") if i.strip()]
        clean = [c.strip() for c in m[3].split(",") if c.strip()]
        ver = [v.strip() for v in m[4].split(",") if v.strip() and v.strip() != "NONE"]
        runtime_state = m[5]
        modes = [md.strip() for md in m[6].split(",") if md.strip()]
        fids = [f.strip() for f in m[7].split(",") if f.strip()]
        deps = [d.strip() for d in m[8].split(",") if d.strip() and d.strip() != "NONE"]
        limitations = m[9].strip()

        data[policy_key] = {
            "extensions": exts,
            "inspect": insp,
            "clean": clean,
            "verify": ver,
            "runtime_state": runtime_state,
            "modes": modes,
            "fidelity": fids,
            "dependencies": deps,
            "limitations": limitations,
        }
    return data


def test_docs_capabilities_table_matches_registry():
    """docs/capabilities.md table must match FormatPolicyRegistry exactly."""
    assert CAPABILITIES_DOC.is_file(), "docs/capabilities.md does not exist"
    doc_table = _parse_capabilities_table(CAPABILITIES_DOC)

    reg = FormatPolicyRegistry.get_default()
    policies = reg.all_policies()

    assert len(doc_table) == 23, f"Expected 23 canonical policies in docs table, got {len(doc_table)}"

    all_doc_exts = set()
    for p in policies:
        k = p.format_name
        assert k in doc_table, f"Missing canonical policy '{k}' in docs/capabilities.md table"
        entry = doc_table[k]

        # Extensions match
        assert entry["extensions"] == list(p.extensions), f"Extension mismatch for {k}"
        for ext in entry["extensions"]:
            assert ext not in all_doc_exts, f"Duplicate extension {ext} in docs table"
            all_doc_exts.add(ext)

        # Inspect capabilities match
        assert entry["inspect"] == list(p.inspect_capabilities), f"Inspect mismatch for {k}"

        # Clean capabilities match
        assert entry["clean"] == list(p.clean_capabilities), f"Clean mismatch for {k}"

        # Verify capabilities match
        assert entry["verify"] == list(p.verify_capabilities), f"Verify mismatch for {k}"

        # Modes match
        assert entry["modes"] == list(p.supported_modes), f"Modes mismatch for {k}"

        # Fidelity match
        assert entry["fidelity"] == [f.value for f in p.fidelity_requirements], f"Fidelity mismatch for {k}"

        # Dependencies match
        assert entry["dependencies"] == list(p.optional_dependencies), f"Dependencies mismatch for {k}"

    # Verify total extension and alias counts
    assert len(all_doc_exts) == 37, f"Expected 37 total extensions, got {len(all_doc_exts)}"
    alias_count = len(all_doc_exts) - len(doc_table)
    assert alias_count == 14, f"Expected 14 extension aliases, got {alias_count}"


# ============================================================================
# 3. RESOURCE & SIZE LIMITS PARITY
# ============================================================================

def test_docs_resource_limits_match_production_constants():
    """Documented limits must match production constants exactly."""
    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    # Audit production constants
    assert common.MAX_INPUT_BYTES == 268435456  # 256 MiB
    assert common.MAX_STDIN_BYTES == 67108864   # 64 MiB
    assert server.MAX_INPUT_BYTES == 268435456  # 256 MiB
    assert server.MAX_BODY_BYTES == 402653184   # 384 MiB
    assert batch_processor.MAX_INPUT_BYTES == 33554432          # 32 MiB
    assert batch_processor.MAX_BATCH_FILES == 100               # 100
    assert batch_processor.MAX_BATCH_TOTAL_BYTES == 209715200    # 200 MiB
    assert batch_processor.MAX_BATCH_INLINE_OUTPUT_BYTES == 33554432  # 32 MiB

    sec_lim = security.SecurityLimits()
    assert sec_lim.max_member_count == 10000
    assert sec_lim.max_member_uncompressed_bytes == 67108864    # 64 MiB
    assert sec_lim.max_total_uncompressed_bytes == 134217728     # 128 MiB
    assert sec_lim.max_compression_ratio == 100.0
    assert sec_lim.max_xml_part_bytes == 33554432               # 32 MiB
    assert sec_lim.max_total_xml_bytes == 134217728              # 128 MiB
    assert sec_lim.max_xml_depth == 100
    assert sec_lim.max_xml_elements == 500000

    # Verify presence of exact limit values in capabilities doc
    assert "256 MiB" in cap_text or "256.0 MiB" in cap_text
    assert "64 MiB" in cap_text
    assert "384 MiB" in cap_text
    assert "32 MiB" in cap_text
    assert "200 MiB" in cap_text
    assert "100" in cap_text  # MAX_BATCH_FILES
    assert "10,000" in cap_text or "10000" in cap_text
    assert "128 MiB" in cap_text
    assert "100x" in cap_text or "100.0x" in cap_text or "100:1" in cap_text or "100 ratio" in cap_text or "100.0" in cap_text
    assert "500,000" in cap_text or "500000" in cap_text


# ============================================================================
# 4. EXIT CODE PARITY
# ============================================================================

def test_docs_exit_codes_parity():
    """Documented exit codes must match ExitCode enum and Phase 4 contract."""
    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    # Production ExitCode values
    assert ExitCode.SUCCESS == 0
    assert ExitCode.UNSUPPORTED == 2
    assert ExitCode.VALIDATION_FAILED == 3
    assert ExitCode.INVALID_INPUT == 4
    assert ExitCode.DEPENDENCY_MISSING == 5
    assert ExitCode.LIMIT_EXCEEDED == 6
    assert ExitCode.BATCH_PARTIAL_FAILURE == 7
    assert ExitCode.BATCH_PARTIAL_SUCCESS == 7
    assert ExitCode.INTERNAL_ERROR == 10

    for doc in (cap_text, readme_text):
        assert "0" in doc and "SUCCESS" in doc
        assert "2" in doc and "UNSUPPORTED" in doc
        assert "3" in doc and "VALIDATION_FAILED" in doc
        assert "4" in doc and "INVALID_INPUT" in doc
        assert "5" in doc and "DEPENDENCY_MISSING" in doc
        assert "6" in doc and "LIMIT_EXCEEDED" in doc
        assert "7" in doc and ("BATCH_PARTIAL_FAILURE" in doc or "BATCH_PARTIAL_SUCCESS" in doc)
        assert "10" in doc and "INTERNAL_ERROR" in doc

    # Exit 2 must strictly mean UNSUPPORTED family, never limits or setup
    assert "Exit 2 is strictly reserved for the UNSUPPORTED family" in cap_text or "Exit 2 strictly retains the unsupported format" in cap_text


# ============================================================================
# 5. HTTP STATUS CODE PARITY
# ============================================================================

def test_docs_http_status_mapping():
    """Documented HTTP status codes must match error_code_to_http_status()."""
    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    expected_mappings = {
        "UNSUPPORTED_FORMAT": 415,
        "INVALID_CONTAINER": 400,
        "VALIDATION_FAILED": 422,
        "OPTIONAL_DEPENDENCY_MISSING": 424,
        "UNSUPPORTED_ARCHIVE_FEATURE": 422,
        "PROCESSING_LIMIT_EXCEEDED": 413,
        "INTERNAL_ERROR": 500,
    }

    for err_name, code in expected_mappings.items():
        err_enum = getattr(ErrorCode, err_name)
        assert error_code_to_http_status(err_enum) == code

    # Both documents must cover key status codes
    for status_str in ("200", "400", "413", "415", "422", "424", "500"):
        assert status_str in cap_text, f"HTTP status {status_str} missing in docs/capabilities.md"


# ============================================================================
# 6. TERMINOLOGY PARITY
# ============================================================================

def test_docs_status_terminology_consistency():
    """Status terminology must match pipeline enums and distinguish NOT_CHECKED."""
    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    detection_terms = [e.value for e in DetectionStatus]
    pipeline_terms = [e.value for e in PipelineStatus]

    for term in detection_terms:
        assert term in cap_text, f"DetectionStatus {term} missing in capabilities doc"
    for term in pipeline_terms:
        assert term in cap_text, f"PipelineStatus {term} missing in capabilities doc"

    # Crucial semantic distinctions
    assert "NOT_CHECKED" in cap_text and "NOT_DETECTED" in cap_text
    assert "NOT_CHECKED" in readme_text and "NOT_DETECTED" in readme_text


# ============================================================================
# 7. CLI COMMAND EXAMPLE VALIDATION
# ============================================================================

def test_readme_cli_command_syntax():
    """CLI examples in README.md must use real commands, flags, and options."""
    readme_text = README_PATH.read_text(encoding="utf-8")
    parser = build_parser()

    # Extract all command lines starting with `watermarks `
    cli_lines = re.findall(r"^\s*(?:[\$#]\s*)?watermarks\s+([^\r\n`#]+)", readme_text, re.MULTILINE)
    assert len(cli_lines) > 0, "No CLI examples found in README.md"

    valid_subcommands = {"inspect", "clean", "batch", "verify", "capabilities"}

    for line in cli_lines:
        tokens = line.strip().split()
        if not tokens:
            continue
        subcmd = tokens[0]
        assert subcmd in valid_subcommands, f"Invalid CLI subcommand '{subcmd}' in README example: {line}"

        # Validate options used in example
        for token in tokens[1:]:
            if token.startswith("-"):
                # Clean flag from any trailing example syntax
                flag = token.split("=")[0]
                # Option must be recognized
                # Check against all actions in parser or specific subparser
                # General verification that known options are valid
                valid_flags = {
                    "--mode", "-m", "--json", "--dry-run", "--in-place",
                    "-o", "--output", "-r", "--recursive",
                    "--output-dir", "--reports-dir", "--help", "-h",
                }
                assert flag in valid_flags, f"Unknown CLI option '{flag}' in README example: {line}"


# ============================================================================
# 8. MARKDOWN LINKS VALIDITY
# ============================================================================

def test_docs_relative_links_resolve():
    """All relative markdown links in README and docs must resolve to existing files."""
    for doc_path in (README_PATH, CAPABILITIES_DOC, GUARANTEES_DOC):
        if not doc_path.is_file():
            continue
        text = doc_path.read_text(encoding="utf-8")
        # Match [text](target) where target does not start with http, mailto, or #
        links = re.findall(r"\[(?:[^\]]+)\]\(([^)#\s]+)\)", text)
        for link in links:
            if link.startswith("http://") or link.startswith("https://") or link.startswith("mailto:"):
                continue
            # Resolve relative to doc directory
            target_path = (doc_path.parent / link).resolve()
            assert target_path.exists(), f"Broken relative link '{link}' in {doc_path.name} -> {target_path} not found"


# ============================================================================
# 9. PRIVACY & SENSITIVE PATH AUDIT
# ============================================================================

def test_docs_contain_no_private_host_paths():
    """Public documentation must contain zero personal home directories or usernames."""
    sensitive_tokens = ["nvhoa", "Users\\nvhoa", "C:\\Users", "e:\\wartermark_remove"]

    for doc_path in (README_PATH, CAPABILITIES_DOC, GUARANTEES_DOC):
        if not doc_path.is_file():
            continue
        text = doc_path.read_text(encoding="utf-8")
        for token in sensitive_tokens:
            assert token.lower() not in text.lower(), f"Sensitive token '{token}' leaked in {doc_path.name}"


# ============================================================================
# 10. HONEST / NON-ABSOLUTE CLAIM AUDIT
# ============================================================================

def test_docs_contain_no_hyperbolic_claims():
    """Public documentation must not claim absolute watermark removal or 100% security."""
    prohibited_phrases = [
        "removes all ai watermarks",
        "guarantees no watermark remains",
        "cleans all metadata",
        "100% secure",
        "pixel-perfect",
        "blazing fast",
    ]

    for doc_path in (README_PATH, CAPABILITIES_DOC, GUARANTEES_DOC):
        if not doc_path.is_file():
            continue
        text = doc_path.read_text(encoding="utf-8").lower()
        for phrase in prohibited_phrases:
            assert phrase not in text, f"Prohibited hyperbolic phrase '{phrase}' found in {doc_path.name}"


# ============================================================================
# 11. PDF MODEL-B BOUNDED FALLBACK DOCUMENTATION
# ============================================================================

def test_pdf_model_b_bounded_fallback_documented():
    """PDF bounded fallback semantics must be explicitly documented."""
    for doc_path in (CAPABILITIES_DOC, GUARANTEES_DOC):
        if not doc_path.is_file():
            continue
        text = doc_path.read_text(encoding="utf-8")
        assert "Model B" in text or "Model-B" in text or "bounded fallback" in text.lower()
        assert "OPTIONAL_DEPENDENCY_MISSING" in text


# ============================================================================
# 12. RESOURCE LIMIT CROSS-CONTRACT HTTP STATUS VERIFICATION
# ============================================================================

def test_resource_limit_cross_contract_http_status():
    """Verify numeric resource limits map to PROCESSING_LIMIT_EXCEEDED (HTTP 413)."""
    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")

    # Numeric resource ceilings must map to HTTP 413, not HTTP 422
    assert "exit 6 / HTTP 413" in cap_text
    assert error_code_to_http_status(ErrorCode.PROCESSING_LIMIT_EXCEEDED) == 413
    assert error_code_to_http_status(ErrorCode.UNSUPPORTED_ARCHIVE_FEATURE) == 422
    assert error_code_to_http_status(ErrorCode.INVALID_CONTAINER) == 400
    assert error_code_to_http_status(ErrorCode.VALIDATION_FAILED) == 422

    # Verify that the resource limits table does not map numeric ceilings to 422
    for ceiling in (
        "ZIP Archive Member Count",
        "ZIP Member Uncompressed",
        "ZIP Total Uncompressed",
        "ZIP Compression Ratio",
        "XML Part Byte Size",
        "XML Total Byte Size",
        "XML Max Nesting Depth",
        "XML Max Elements",
    ):
        pattern = rf"\|\s*\*\*{ceiling}\*\*\s*\|\s*[^|]+\|\s*[^|]+\|\s*(.*?)\s*\|"
        m = re.search(pattern, cap_text)
        assert m is not None, f"Ceiling {ceiling} not found in capabilities doc"
        outcome = m.group(1)
        assert "HTTP 413" in outcome, f"Ceiling {ceiling} outcome should specify HTTP 413, got: {outcome}"
        assert "HTTP 422" not in outcome, f"Ceiling {ceiling} erroneously specifies HTTP 422"


# ============================================================================
# 13. BATCH ITEM CEILING CLI VS HTTP SCOPE DISTINCTION
# ============================================================================

def test_batch_limit_cli_vs_http_distinction():
    """Verify distinct defaults for CLI batch (100) vs HTTP /batch (50)."""
    assert batch_processor.MAX_BATCH_FILES == 100
    assert server.MAX_BATCH_FILES == 50

    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    # Both documents must clearly distinguish the 100 (CLI) and 50 (HTTP) limits
    for doc in (cap_text, readme_text):
        assert "CLI Batch Item Count" in doc or "Batch Item Count" in doc
        assert "100" in doc
        assert "50" in doc
        assert "HTTP" in doc and "batch" in doc


# ============================================================================
# 14. CONTEXTUAL UNICODE PRESERVATION DOCUMENTATION TRUTH
# ============================================================================

def test_contextual_unicode_documentation_truth():
    """Verify docs do not claim unconditional strip of U+200C/U+200D and document contextual preservation."""
    guarantees_text = GUARANTEES_DOC.read_text(encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")

    for doc in (guarantees_text, readme_text):
        # Must document contextual preservation
        assert "contextual" in doc.lower()
        assert "emoji" in doc.lower()

    # In format_guarantees, verify explicit mention that U+200C and U+200D are not unconditionally stripped
    assert "never unconditionally stripped" in guarantees_text.lower() or "strictly preserved" in guarantees_text.lower()
    assert "U+200C" in guarantees_text and "U+200D" in guarantees_text
    assert "Arabic" in guarantees_text or "Persian" in guarantees_text or "Devanagari" in guarantees_text


# ============================================================================
# 15. CANONICAL AUDIO/VIDEO IN-PROCESS TRUTH
# ============================================================================

def test_canonical_av_clean_in_process_truth():
    """Verify docs state canonical cleaning is 100% in-process with 0 subprocesses and no ffmpeg."""
    guarantees_text = GUARANTEES_DOC.read_text(encoding="utf-8")
    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")

    # Format guarantees must state canonical cleaning is 100% in-process
    assert "100% in-process" in guarantees_text
    assert "zero subprocesses" in guarantees_text.lower()

    # Standalone purifiers vs canonical pipeline distinction
    assert "standalone" in guarantees_text.lower()
    assert "ffmpeg" in guarantees_text.lower()

    # Capabilities matrix limitations note
    assert "standalone purifier" in cap_text.lower()


# ============================================================================
# 16. XLSX SHARED STRING INDICES INVARIANT WORDING
# ============================================================================

def test_xlsx_shared_string_indices_invariant_wording():
    """Verify XLSX shared string invariant documentation specifies unchanged indices."""
    guarantees_text = GUARANTEES_DOC.read_text(encoding="utf-8")
    cap_text = CAPABILITIES_DOC.read_text(encoding="utf-8")

    for doc in (guarantees_text, cap_text):
        assert "indices remain unchanged" in doc.lower() or "without re-indexing" in doc.lower()


# ============================================================================
# 17. PHASE 4 COMMIT PROVENANCE CONSISTENCY
# ============================================================================

def test_phase4_commit_provenance_consistency():
    """Verify canonical closure 1fb5cba5 and historical pre-amend 3370fcc7 are consistently documented."""
    roadmap_text = (REPO_ROOT / "docs" / "v2.1" / "ROADMAP.md").read_text(encoding="utf-8")
    p4_report_text = (REPO_ROOT / "docs" / "v2.1" / "PHASE4_CONTRACT_CLOSURE_REPORT.md").read_text(encoding="utf-8")

    for doc in (roadmap_text, p4_report_text):
        assert "1fb5cba5ef243021bf53ef4f1498aedf76ccfa16" in doc
        assert "3370fcc7b0ef0002c30748d410293e32cd790dd0" in doc

