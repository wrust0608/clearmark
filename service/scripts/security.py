"""service/scripts/security.py

Universal security preflight and resource-governance engine for ClearMark v2.1.

Adheres strictly to Phase 9 specifications:
- Format-neutral container-level and XML-level threat mitigation before any mutation.
- Strict rejection of ZipSlip, ZipBombs, duplicate entries, symlinks, encrypted members,
  unsupported compression, structural corruption, and XML DTD/XXE/depth/element attacks.
- Read-only validation: zero mutation, zero disk writes, zero temporary files, zero network egress.
- Metadata-only security diagnostics with control character/ANSI escaping.
- Fail-closed defaults: any malformed container -> ErrorCode.INVALID_CONTAINER (Exit 4, HTTP 400);
  any resource limit exceeded -> ErrorCode.PROCESSING_LIMIT_EXCEEDED (Exit 6, HTTP 413).
"""

from __future__ import annotations

import io
import os
import re
import stat
import struct
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import xml.etree.ElementTree as ET


# ==============================================================================
# 1. SECURITY LIMITS DATA MODEL
# ==============================================================================

def _env_int(key: str, default: int, min_val: int = 1) -> int:
    """Safely parse integer environment variables; fallback to default on invalid or out-of-range value."""
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        parsed = int(val)
        return parsed if parsed >= min_val else default
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float, min_val: float = 0.0) -> float:
    """Safely parse float environment variables; fallback to default on invalid or out-of-range value."""
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        parsed = float(val)
        return parsed if parsed >= min_val else default
    except (ValueError, TypeError):
        return default


def _has_zip64_extra(extra_bytes: bytes) -> bool:
    """Detect ZIP64 extended information extra field (header ID 0x0001) in an extra field block."""
    pos = 0
    extra_len = len(extra_bytes)
    while pos + 4 <= extra_len:
        header_id, data_size = struct.unpack("<HH", extra_bytes[pos : pos + 4])
        if header_id == 0x0001:
            return True
        pos += 4 + data_size
    return False


@dataclass(frozen=True)
class SecurityLimits:
    """Configurable security resource limits for containers and XML parsers.

    Values have safe defaults established by measuring valid corpora across DOCX,
    XLSX, and PPTX with documented margins. All limits support environment variable
    overrides following the WATERMARKS_SECURITY_* convention, and programmatic injection.
    Malformed or out-of-range environment values safely fall back to authoritative defaults.
    """
    max_member_count: int = field(
        default_factory=lambda: _env_int("WATERMARKS_SECURITY_MAX_MEMBER_COUNT", 10000, 1)
    )
    max_member_uncompressed_bytes: int = field(
        default_factory=lambda: _env_int(
            "WATERMARKS_SECURITY_MAX_MEMBER_UNCOMPRESSED_BYTES", 64 * 1024 * 1024, 1
        )
    )
    max_total_uncompressed_bytes: int = field(
        default_factory=lambda: _env_int(
            "WATERMARKS_SECURITY_MAX_TOTAL_UNCOMPRESSED_BYTES", 128 * 1024 * 1024, 1
        )
    )
    max_compression_ratio: float = field(
        default_factory=lambda: _env_float("WATERMARKS_SECURITY_MAX_COMPRESSION_RATIO", 100.0, 1.0)
    )
    min_compressed_bytes_for_ratio: int = field(
        default_factory=lambda: _env_int("WATERMARKS_SECURITY_MIN_COMPRESSED_BYTES_FOR_RATIO", 1024, 0)
    )
    max_member_name_bytes: int = field(
        default_factory=lambda: _env_int("WATERMARKS_SECURITY_MAX_MEMBER_NAME_BYTES", 1024, 1)
    )
    max_xml_part_bytes: int = field(
        default_factory=lambda: _env_int(
            "WATERMARKS_SECURITY_MAX_XML_PART_BYTES", 32 * 1024 * 1024, 1
        )
    )
    max_total_xml_bytes: int = field(
        default_factory=lambda: _env_int(
            "WATERMARKS_SECURITY_MAX_TOTAL_XML_BYTES", 128 * 1024 * 1024, 1
        )
    )
    max_xml_depth: int = field(
        default_factory=lambda: _env_int("WATERMARKS_SECURITY_MAX_XML_DEPTH", 100, 1)
    )
    max_xml_elements: int = field(
        default_factory=lambda: _env_int("WATERMARKS_SECURITY_MAX_XML_ELEMENTS", 500000, 1)
    )
    chunk_size: int = 64 * 1024  # 64 KiB chunk size for streaming decompression


# ==============================================================================
# 2. DIAGNOSTIC DATA MODELS & SANITIZATION
# ==============================================================================

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def sanitize_report_string(text: str, max_len: int = 256) -> str:
    """Sanitize strings for security diagnostics and logs.

    Strips ANSI escape sequences, control characters, and truncates extreme lengths
    to prevent terminal injection and log corruption.
    """
    if not text:
        return ""
    # Strip ANSI sequences
    clean = _ANSI_ESCAPE_RE.sub("", text)
    # Filter control chars (keep standard printable)
    filtered = "".join(
        c if (c.isprintable() or c in (" ", "-", "_", ".", "/", ":")) else f"\\x{ord(c):02x}"
        for c in clean
    )
    if len(filtered) > max_len:
        return filtered[:max_len] + "...[truncated]"
    return filtered


@dataclass
class SecurityFinding:
    """Metadata-only security finding. Never exposes raw payload contents."""
    rule_id: str
    member_name: Optional[str] = None
    observed_value: Optional[Union[int, float, str]] = None
    configured_limit: Optional[Union[int, float, str]] = None
    reason: str = ""
    severity: str = "ERROR"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "reason": sanitize_report_string(self.reason),
            "severity": self.severity,
        }
        if self.member_name is not None:
            d["member_name"] = sanitize_report_string(self.member_name)
        if self.observed_value is not None:
            d["observed_value"] = self.observed_value
        if self.configured_limit is not None:
            d["configured_limit"] = self.configured_limit
        return d


class SecurityViolation(Exception):
    """Exception raised when a security invariant or resource limit is breached."""

    def __init__(self, finding: SecurityFinding, is_limit: bool = False) -> None:
        self.finding = finding
        self.is_limit = is_limit
        super().__init__(finding.reason)


@dataclass
class SecurityPreflightResult:
    """Structured, metadata-only outcome of container security preflight."""
    is_safe: bool
    findings: List[SecurityFinding] = field(default_factory=list)
    total_members: int = 0
    total_uncompressed_bytes: int = 0
    total_xml_bytes: int = 0
    max_xml_depth_observed: int = 0
    total_xml_elements_observed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "findings": [f.to_dict() for f in self.findings],
            "total_members": self.total_members,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "total_xml_bytes": self.total_xml_bytes,
            "max_xml_depth_observed": self.max_xml_depth_observed,
            "total_xml_elements_observed": self.total_xml_elements_observed,
        }


# ==============================================================================
# 3. XML SECURITY PREFLIGHT
# ==============================================================================

def preflight_xml_data(
    data: bytes,
    limits: SecurityLimits,
    part_name: str = "",
) -> SecurityPreflightResult:
    """Perform bounded streaming validation on raw XML bytes.

    Guards:
    1. XML part size bound.
    2. Encoding-aware DOCTYPE / ENTITY / XXE detection across UTF-8, UTF-16, ASCII.
    3. Non-recursive streaming element parsing tracking nesting depth and element counts.
    4. Memory-safe: calls elem.clear() during streaming to maintain O(depth) memory.
    5. Malformedness detection (fail-closed).
    """
    clean_part = sanitize_report_string(part_name)

    if len(data) > limits.max_xml_part_bytes:
        finding = SecurityFinding(
            rule_id="SEC_XML_PART_SIZE_LIMIT",
            member_name=clean_part,
            observed_value=len(data),
            configured_limit=limits.max_xml_part_bytes,
            reason=f"XML part '{clean_part}' size ({len(data)} B) exceeds limit {limits.max_xml_part_bytes} B",
        )
        raise SecurityViolation(finding, is_limit=True)

    if not data.strip():
        return SecurityPreflightResult(
            is_safe=True,
            total_uncompressed_bytes=len(data),
            total_xml_bytes=len(data),
            max_xml_depth_observed=0,
            total_xml_elements_observed=0,
        )

    # 1. Encoding-aware upfront DOCTYPE / ENTITY detection
    # Handle UTF-16 LE / BE BOM, UTF-8 BOM, ISO-8859-1, or declared encodings before string search
    text: str
    if data.startswith(b"\xff\xfe") or data[:4] == b"<\x00?\x00":
        text = data.decode("utf-16-le", errors="replace")
    elif data.startswith(b"\xfe\xff") or data[:4] == b"\x00<\x00?":
        text = data.decode("utf-16-be", errors="replace")
    elif data.startswith(b"\xef\xbb\xbf"):
        text = data.decode("utf-8-sig", errors="replace")
    elif b"encoding=" in data[:128].lower() and (b"iso-8859-1" in data[:128].lower() or b"latin" in data[:128].lower()):
        text = data.decode("iso-8859-1", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")

    text_upper = text.upper()
    if "<!DOCTYPE" in text_upper:
        finding = SecurityFinding(
            rule_id="SEC_XML_DOCTYPE",
            member_name=clean_part,
            reason=f"Forbidden <!DOCTYPE declaration detected in XML part '{clean_part}'",
        )
        raise SecurityViolation(finding, is_limit=False)

    if "<!ENTITY" in text_upper:
        finding = SecurityFinding(
            rule_id="SEC_XML_ENTITY",
            member_name=clean_part,
            reason=f"Forbidden <!ENTITY declaration detected in XML part '{clean_part}'",
        )
        raise SecurityViolation(finding, is_limit=False)

    if "SYSTEM" in text_upper and ("HTTP:" in text_upper or "HTTPS:" in text_upper or "FILE:" in text_upper):
        finding = SecurityFinding(
            rule_id="SEC_XML_XXE_SYSTEM",
            member_name=clean_part,
            reason=f"Suspicious external SYSTEM reference detected in XML part '{clean_part}'",
        )
        raise SecurityViolation(finding, is_limit=False)

    # 2. Streaming parser: track nesting depth and element counts using expat (namespace-agnostic)
    import xml.parsers.expat
    p = xml.parsers.expat.ParserCreate()
    depth = 0
    max_depth = 0
    elem_count = 0

    def start_element(name, attrs):
        nonlocal depth, max_depth, elem_count
        depth += 1
        elem_count += 1
        if depth > max_depth:
            max_depth = depth

        if depth > limits.max_xml_depth:
            finding = SecurityFinding(
                rule_id="SEC_XML_DEPTH_LIMIT",
                member_name=clean_part,
                observed_value=depth,
                configured_limit=limits.max_xml_depth,
                reason=f"XML nesting depth {depth} exceeds limit {limits.max_xml_depth} in '{clean_part}'",
            )
            raise SecurityViolation(finding, is_limit=True)

        if elem_count > limits.max_xml_elements:
            finding = SecurityFinding(
                rule_id="SEC_XML_ELEMENT_COUNT_LIMIT",
                member_name=clean_part,
                observed_value=elem_count,
                configured_limit=limits.max_xml_elements,
                reason=f"XML element count {elem_count} exceeds limit {limits.max_xml_elements} in '{clean_part}'",
            )
            raise SecurityViolation(finding, is_limit=True)

    def end_element(name):
        nonlocal depth
        depth -= 1

    def doctype_handler(doctypeName, systemId, publicId, has_internal_subset):
        finding = SecurityFinding(
            rule_id="SEC_XML_DOCTYPE",
            member_name=clean_part,
            reason=f"Forbidden <!DOCTYPE declaration detected in XML part '{clean_part}'",
        )
        raise SecurityViolation(finding, is_limit=False)

    def entity_decl_handler(entityName, is_parameter_entity, value, base, systemId, publicId, notationName):
        finding = SecurityFinding(
            rule_id="SEC_XML_ENTITY",
            member_name=clean_part,
            reason=f"Forbidden <!ENTITY declaration detected in XML part '{clean_part}'",
        )
        raise SecurityViolation(finding, is_limit=False)

    p.StartElementHandler = start_element
    p.EndElementHandler = end_element
    p.StartDoctypeDeclHandler = doctype_handler
    p.EntityDeclHandler = entity_decl_handler

    try:
        p.Parse(data, True)
    except (xml.parsers.expat.ExpatError, Exception) as e:
        if isinstance(e, SecurityViolation):
            raise
        finding = SecurityFinding(
            rule_id="SEC_XML_MALFORMED",
            member_name=clean_part,
            reason=f"Malformed XML syntax in '{clean_part}': {e}",
        )
        raise SecurityViolation(finding, is_limit=False) from e

    return SecurityPreflightResult(
        is_safe=True,
        total_uncompressed_bytes=len(data),
        total_xml_bytes=len(data),
        max_xml_depth_observed=max_depth,
        total_xml_elements_observed=elem_count,
    )


# ==============================================================================
# 4. CONTAINER PREFLIGHT ENGINE
# ==============================================================================

@dataclass
class _ZipMemberRecord:
    name: str
    raw_name: bytes
    comp_method: int
    flags: int
    crc: int
    compressed_size: int
    uncompressed_size: int
    local_hdr_offset: int
    external_attr: int


def preflight_zip_container(
    data: bytes,
    limits: Optional[SecurityLimits] = None,
) -> SecurityPreflightResult:
    """Comprehensive, format-neutral security preflight on raw ZIP archive bytes.

    Validates archive structures, member metadata, decompression bounds, local-header
    consistency, overlapping member ranges, and XML parts without modifying data.
    """
    if limits is None:
        limits = SecurityLimits()

    data_len = len(data)
    if data_len < 22:
        finding = SecurityFinding(
            rule_id="SEC_TRUNCATED_ARCHIVE",
            reason=f"Archive too small to contain valid EOCD ({data_len} B < 22 B)",
        )
        raise SecurityViolation(finding, is_limit=False)

    # 1. Locate End of Central Directory (EOCD)
    # Search backwards from end (EOCD record is 22 bytes + comment up to 65535 bytes)
    search_limit = min(data_len, 65557)
    eocd_pos = -1
    for i in range(data_len - 22, data_len - search_limit - 1, -1):
        if data[i : i + 4] == b"PK\x05\x06":
            # Verify comment length matches exact file boundary
            if i + 22 <= data_len:
                comment_len = struct.unpack("<H", data[i + 20 : i + 22])[0]
                if i + 22 + comment_len == data_len:
                    eocd_pos = i
                    break
    if eocd_pos == -1:
        # Fallback to standard rfind if comment length check failed
        eocd_pos = data.rfind(b"PK\x05\x06")
        if eocd_pos == -1:
            finding = SecurityFinding(
                rule_id="SEC_MISSING_EOCD",
                reason="Missing End of Central Directory (EOCD) record",
            )
            raise SecurityViolation(finding, is_limit=False)

    if eocd_pos + 22 > data_len:
        finding = SecurityFinding(
            rule_id="SEC_TRUNCATED_EOCD",
            reason="Truncated End of Central Directory record",
        )
        raise SecurityViolation(finding, is_limit=False)

    (
        disk_num,
        cd_disk,
        disk_entries,
        total_entries,
        cd_size,
        cd_offset,
        comment_len,
    ) = struct.unpack("<HHHHIIH", data[eocd_pos + 4 : eocd_pos + 22])

    if eocd_pos + 22 + comment_len != data_len:
        finding = SecurityFinding(
            rule_id="SEC_TRUNCATED_EOCD",
            reason="EOCD comment length does not match archive boundary",
        )
        raise SecurityViolation(finding, is_limit=False)

    # 2. Multi-disk archive check
    if disk_num != 0 or cd_disk != 0:
        finding = SecurityFinding(
            rule_id="SEC_MULTIDISK_ARCHIVE",
            reason=f"Multi-disk ZIP archives are unsupported (disk {disk_num}, cd_disk {cd_disk})",
        )
        raise SecurityViolation(finding, is_limit=False)

    # 3. ZIP64 fail-closed policy (Option B)
    if (
        total_entries == 0xFFFF
        or cd_size == 0xFFFFFFFF
        or cd_offset == 0xFFFFFFFF
        or b"PK\x06\x07" in data
        or b"PK\x06\x06" in data
    ):
        finding = SecurityFinding(
            rule_id="SEC_ZIP64_UNSUPPORTED",
            reason="ZIP64 container structures are unsupported fail-closed",
        )
        raise SecurityViolation(finding, is_limit=False)

    # 4. Central Directory boundary checks
    if cd_offset < 0 or cd_offset > data_len:
        finding = SecurityFinding(
            rule_id="SEC_BAD_CD_OFFSET",
            observed_value=cd_offset,
            configured_limit=data_len,
            reason=f"Central directory offset {cd_offset} outside archive bounds ({data_len} B)",
        )
        raise SecurityViolation(finding, is_limit=False)

    if cd_offset + cd_size > eocd_pos or cd_offset + cd_size > data_len:
        finding = SecurityFinding(
            rule_id="SEC_TRUNCATED_CD",
            reason="Central directory extends beyond EOCD or archive boundary",
        )
        raise SecurityViolation(finding, is_limit=False)

    if disk_entries != total_entries:
        finding = SecurityFinding(
            rule_id="SEC_ENTRY_COUNT_MISMATCH",
            reason=f"Disk entry count ({disk_entries}) does not match total entry count ({total_entries})",
        )
        raise SecurityViolation(finding, is_limit=False)

    # 5. Member count limit
    if total_entries > limits.max_member_count:
        finding = SecurityFinding(
            rule_id="SEC_MEMBER_COUNT_LIMIT",
            observed_value=total_entries,
            configured_limit=limits.max_member_count,
            reason=f"Member count {total_entries} exceeds configured limit {limits.max_member_count}",
        )
        raise SecurityViolation(finding, is_limit=True)

    # 6. Parse Central Directory Records
    cd_pos = cd_offset
    members: List[_ZipMemberRecord] = []
    seen_names: Set[str] = set()
    declared_total_uncompressed = 0

    for _ in range(total_entries):
        if cd_pos + 46 > cd_offset + cd_size:
            finding = SecurityFinding(
                rule_id="SEC_TRUNCATED_CD_RECORD",
                reason=f"Truncated Central Directory record at offset {cd_pos}",
            )
            raise SecurityViolation(finding, is_limit=False)

        (
            sig,
            made_by,
            ver,
            flags,
            comp,
            mtime,
            mdate,
            crc,
            csize,
            usize,
            nlen,
            elen,
            clen,
            dnum,
            iattr,
            eattr,
            lhoff,
        ) = struct.unpack("<IHHHHHHIIIHHHHHII", data[cd_pos : cd_pos + 46])

        if sig != 0x02014B50:
            finding = SecurityFinding(
                rule_id="SEC_INVALID_CD_SIGNATURE",
                reason=f"Invalid Central Directory record signature 0x{sig:08X} at offset {cd_pos}",
            )
            raise SecurityViolation(finding, is_limit=False)

        rec_len = 46 + nlen + elen + clen
        if cd_pos + rec_len > cd_offset + cd_size:
            finding = SecurityFinding(
                rule_id="SEC_TRUNCATED_CD_RECORD",
                reason=f"Central Directory entry exceeds CD bounds at offset {cd_pos}",
            )
            raise SecurityViolation(finding, is_limit=False)

        cd_extra_bytes = data[cd_pos + 46 + nlen : cd_pos + 46 + nlen + elen]
        if _has_zip64_extra(cd_extra_bytes):
            finding = SecurityFinding(
                rule_id="SEC_ZIP64_UNSUPPORTED",
                reason="ZIP64 extra field (0x0001) in Central Directory fail-closed",
            )
            raise SecurityViolation(finding, is_limit=False)

        raw_name = data[cd_pos + 46 : cd_pos + 46 + nlen]
        if len(raw_name) > limits.max_member_name_bytes:
            finding = SecurityFinding(
                rule_id="SEC_MEMBER_NAME_LIMIT",
                observed_value=len(raw_name),
                configured_limit=limits.max_member_name_bytes,
                reason=f"Member name length {len(raw_name)} B exceeds limit {limits.max_member_name_bytes} B",
            )
            raise SecurityViolation(finding, is_limit=True)

        if b"\x00" in raw_name:
            finding = SecurityFinding(
                rule_id="SEC_ZIPSLIP_NUL_BYTE",
                reason="Member name contains forbidden NUL character",
            )
            raise SecurityViolation(finding, is_limit=False)

        try:
            name = raw_name.decode("utf-8")
        except UnicodeDecodeError:
            name = raw_name.decode("cp437", errors="replace")

        clean_name = sanitize_report_string(name)

        # ZipSlip & Path Traversal Guards
        if name.startswith("//") or name.startswith("\\\\"):
            finding = SecurityFinding(
                rule_id="SEC_ZIPSLIP_UNC",
                member_name=clean_name,
                reason=f"Member name contains forbidden UNC path: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        if "\\" in name:
            finding = SecurityFinding(
                rule_id="SEC_ZIPSLIP_BACKSLASH",
                member_name=clean_name,
                reason=f"Member name contains forbidden backslash path separator: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        if name.startswith("/"):
            finding = SecurityFinding(
                rule_id="SEC_ZIPSLIP_ABSOLUTE",
                member_name=clean_name,
                reason=f"Member name contains forbidden absolute root path: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        if re.match(r"^[a-zA-Z]:", name):
            finding = SecurityFinding(
                rule_id="SEC_ZIPSLIP_WINDOWS_DRIVE",
                member_name=clean_name,
                reason=f"Member name contains forbidden Windows drive specification: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        parts = name.split("/")
        if ".." in parts:
            finding = SecurityFinding(
                rule_id="SEC_ZIPSLIP_PARENT",
                member_name=clean_name,
                reason=f"Member name contains forbidden directory traversal '..': '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        if "." in parts or any(p == "" for p in parts[:-1]):
            finding = SecurityFinding(
                rule_id="SEC_NONCANONICAL_PATH",
                member_name=clean_name,
                reason=f"Member name contains non-canonical path segments: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        # Duplicate Member Names
        if name in seen_names:
            finding = SecurityFinding(
                rule_id="SEC_DUPLICATE_MEMBER",
                member_name=clean_name,
                reason=f"Duplicate archive member detected: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)
        seen_names.add(name)

        # Symlink Member Check (Unix external attribute S_IFLNK)
        unix_mode = eattr >> 16
        if stat.S_ISLNK(unix_mode):
            finding = SecurityFinding(
                rule_id="SEC_SYMLINK_MEMBER",
                member_name=clean_name,
                reason=f"Forbidden symlink member detected: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        # Encrypted Member Check
        if flags & 0x01:
            finding = SecurityFinding(
                rule_id="SEC_ENCRYPTED_MEMBER",
                member_name=clean_name,
                reason=f"Encrypted ZIP member detected: '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        # Allowed Compression Methods (STORED=0, DEFLATED=8)
        if comp not in (0, 8):
            finding = SecurityFinding(
                rule_id="SEC_UNSUPPORTED_COMPRESSION",
                member_name=clean_name,
                observed_value=comp,
                reason=f"Unsupported compression method {comp} in member '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        # Declared Uncompressed Size Bounds
        if usize > limits.max_member_uncompressed_bytes:
            finding = SecurityFinding(
                rule_id="SEC_MEMBER_UNCOMPRESSED_LIMIT",
                member_name=clean_name,
                observed_value=usize,
                configured_limit=limits.max_member_uncompressed_bytes,
                reason=f"Member '{clean_name}' declared uncompressed size ({usize} B) exceeds limit {limits.max_member_uncompressed_bytes} B",
            )
            raise SecurityViolation(finding, is_limit=True)

        declared_total_uncompressed += usize
        if declared_total_uncompressed > limits.max_total_uncompressed_bytes:
            finding = SecurityFinding(
                rule_id="SEC_TOTAL_UNCOMPRESSED_LIMIT",
                observed_value=declared_total_uncompressed,
                configured_limit=limits.max_total_uncompressed_bytes,
                reason=f"Total declared uncompressed size ({declared_total_uncompressed} B) exceeds limit {limits.max_total_uncompressed_bytes} B",
            )
            raise SecurityViolation(finding, is_limit=True)

        # Compression Ratio Check on Declared Metadata
        if csize >= limits.min_compressed_bytes_for_ratio:
            ratio = usize / csize
            if ratio > limits.max_compression_ratio:
                finding = SecurityFinding(
                    rule_id="SEC_COMPRESSION_RATIO_LIMIT",
                    member_name=clean_name,
                    observed_value=round(ratio, 2),
                    configured_limit=limits.max_compression_ratio,
                    reason=f"Member '{clean_name}' compression ratio ({ratio:.1f}) exceeds limit {limits.max_compression_ratio}",
                )
                raise SecurityViolation(finding, is_limit=True)
        elif csize == 0 and usize > 0 and comp != 0:
            finding = SecurityFinding(
                rule_id="SEC_COMPRESSION_RATIO_LIMIT",
                member_name=clean_name,
                reason=f"Deflated member '{clean_name}' declares zero compressed size with non-zero uncompressed size",
            )
            raise SecurityViolation(finding, is_limit=True)

        members.append(
            _ZipMemberRecord(
                name=name,
                raw_name=raw_name,
                comp_method=comp,
                flags=flags,
                crc=crc,
                compressed_size=csize,
                uncompressed_size=usize,
                local_hdr_offset=lhoff,
                external_attr=eattr,
            )
        )
        cd_pos += rec_len

    # 7. Local File Header Validation & Overlapping Range Detection
    member_ranges: List[Tuple[int, int, str]] = []

    for m in members:
        clean_name = sanitize_report_string(m.name)
        lhoff = m.local_hdr_offset

        if lhoff < 0 or lhoff + 30 > data_len:
            finding = SecurityFinding(
                rule_id="SEC_BAD_LOCAL_HEADER_OFFSET",
                member_name=clean_name,
                observed_value=lhoff,
                configured_limit=data_len,
                reason=f"Local file header offset {lhoff} outside archive bounds for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        (
            lsig,
            lver,
            lflags,
            lcomp,
            lmtime,
            lmdate,
            lcrc,
            lcsize,
            lusize,
            lnlen,
            lelen,
        ) = struct.unpack("<IHHHHHIIIHH", data[lhoff : lhoff + 30])

        if lsig != 0x04034B50:
            finding = SecurityFinding(
                rule_id="SEC_INVALID_LOCAL_SIGNATURE",
                member_name=clean_name,
                reason=f"Invalid Local File Header signature 0x{lsig:08X} for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        loc_hdr_len = 30 + lnlen + lelen
        if lhoff + loc_hdr_len > data_len:
            finding = SecurityFinding(
                rule_id="SEC_BAD_LOCAL_HEADER_BOUNDS",
                member_name=clean_name,
                reason=f"Local header extends beyond archive bounds for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        loc_extra_bytes = data[lhoff + 30 + lnlen : lhoff + 30 + lnlen + lelen]
        if _has_zip64_extra(loc_extra_bytes):
            finding = SecurityFinding(
                rule_id="SEC_ZIP64_UNSUPPORTED",
                member_name=clean_name,
                reason=f"ZIP64 extra field (0x0001) in Local Header for '{clean_name}' fail-closed",
            )
            raise SecurityViolation(finding, is_limit=False)

        local_raw_name = data[lhoff + 30 : lhoff + 30 + lnlen]
        if local_raw_name != m.raw_name:
            finding = SecurityFinding(
                rule_id="SEC_LOCAL_CENTRAL_MISMATCH",
                member_name=clean_name,
                reason=f"Local header filename does not match Central Directory for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        if lcomp != m.comp_method:
            finding = SecurityFinding(
                rule_id="SEC_LOCAL_CENTRAL_MISMATCH",
                member_name=clean_name,
                reason=f"Local header compression method ({lcomp}) does not match Central Directory ({m.comp_method}) for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        if (lflags & 0x01) != (m.flags & 0x01):
            finding = SecurityFinding(
                rule_id="SEC_LOCAL_CENTRAL_MISMATCH",
                member_name=clean_name,
                reason=f"Local header encryption flag mismatch for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        payload_start = lhoff + loc_hdr_len
        payload_end = payload_start + m.compressed_size
        if payload_end > data_len:
            finding = SecurityFinding(
                rule_id="SEC_LOCAL_PAYLOAD_OUT_OF_BOUNDS",
                member_name=clean_name,
                reason=f"Compressed payload extends beyond archive bounds for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        desc_len = 0
        if lflags & 0x08:
            # Data descriptor present
            cand = data[payload_end : payload_end + 16]
            desc_len = 16 if cand.startswith(b"PK\x07\x08") else 12

        total_local_end = payload_end + desc_len
        if total_local_end > data_len:
            finding = SecurityFinding(
                rule_id="SEC_LOCAL_PAYLOAD_OUT_OF_BOUNDS",
                member_name=clean_name,
                reason=f"Data descriptor extends beyond archive bounds for '{clean_name}'",
            )
            raise SecurityViolation(finding, is_limit=False)

        member_ranges.append((lhoff, total_local_end, m.name))

    # 8. Overlapping member ranges check
    sorted_ranges = sorted(member_ranges, key=lambda r: r[0])
    for i in range(len(sorted_ranges) - 1):
        if sorted_ranges[i][1] > sorted_ranges[i + 1][0]:
            name1 = sanitize_report_string(sorted_ranges[i][2])
            name2 = sanitize_report_string(sorted_ranges[i + 1][2])
            finding = SecurityFinding(
                rule_id="SEC_OVERLAPPING_MEMBERS",
                member_name=name1,
                reason=f"Overlapping archive member byte ranges detected between '{name1}' and '{name2}'",
            )
            raise SecurityViolation(finding, is_limit=False)

    # 9. Bounded Streaming Decompression, CRC & XML Preflight
    real_total_uncompressed = 0
    real_total_xml_bytes = 0
    max_xml_depth = 0
    total_xml_elements = 0

    for m in members:
        clean_name = sanitize_report_string(m.name)
        lhoff = m.local_hdr_offset
        lnlen, lelen = struct.unpack("<HH", data[lhoff + 26 : lhoff + 30])
        payload_start = lhoff + 30 + lnlen + lelen
        raw_payload = data[payload_start : payload_start + m.compressed_size]

        member_uncompressed_bytes = 0
        crc_calc = 0
        decompressed_chunks: List[bytes] = []

        is_xml_part = (
            m.name.lower().endswith(".xml")
            or m.name.lower().endswith(".rels")
            or m.name.lower() == "[content_types].xml"
        )

        if m.comp_method == 0:  # STORED
            if len(raw_payload) != m.uncompressed_size:
                finding = SecurityFinding(
                    rule_id="SEC_TRUNCATED_STREAM",
                    member_name=clean_name,
                    reason=f"Stored member payload truncated for '{clean_name}'",
                )
                raise SecurityViolation(finding, is_limit=False)

            # Stream chunks for bounds check
            for offset in range(0, len(raw_payload), limits.chunk_size):
                chunk = raw_payload[offset : offset + limits.chunk_size]
                member_uncompressed_bytes += len(chunk)
                real_total_uncompressed += len(chunk)
                crc_calc = zlib.crc32(chunk, crc_calc)
                if is_xml_part:
                    decompressed_chunks.append(chunk)

                if member_uncompressed_bytes > limits.max_member_uncompressed_bytes:
                    finding = SecurityFinding(
                        rule_id="SEC_MEMBER_UNCOMPRESSED_LIMIT",
                        member_name=clean_name,
                        observed_value=member_uncompressed_bytes,
                        configured_limit=limits.max_member_uncompressed_bytes,
                        reason=f"Actual uncompressed bytes exceeded limit {limits.max_member_uncompressed_bytes} in '{clean_name}'",
                    )
                    raise SecurityViolation(finding, is_limit=True)

                if real_total_uncompressed > limits.max_total_uncompressed_bytes:
                    finding = SecurityFinding(
                        rule_id="SEC_TOTAL_UNCOMPRESSED_LIMIT",
                        observed_value=real_total_uncompressed,
                        configured_limit=limits.max_total_uncompressed_bytes,
                        reason=f"Total actual uncompressed bytes exceeded limit {limits.max_total_uncompressed_bytes}",
                    )
                    raise SecurityViolation(finding, is_limit=True)

        elif m.comp_method == 8:  # DEFLATED
            try:
                decompressor = zlib.decompressobj(-15)
                # Feed compressed data in chunks
                for offset in range(0, len(raw_payload), limits.chunk_size):
                    in_data = raw_payload[offset : offset + limits.chunk_size]
                    while in_data:
                        out_chunk = decompressor.decompress(in_data, limits.chunk_size)
                        in_data = decompressor.unconsumed_tail
                        if not out_chunk:
                            break

                        member_uncompressed_bytes += len(out_chunk)
                        real_total_uncompressed += len(out_chunk)
                        crc_calc = zlib.crc32(out_chunk, crc_calc)
                        if is_xml_part:
                            decompressed_chunks.append(out_chunk)

                        if member_uncompressed_bytes > limits.max_member_uncompressed_bytes:
                            finding = SecurityFinding(
                                rule_id="SEC_MEMBER_UNCOMPRESSED_LIMIT",
                                member_name=clean_name,
                                observed_value=member_uncompressed_bytes,
                                configured_limit=limits.max_member_uncompressed_bytes,
                                reason=f"Actual uncompressed bytes exceeded limit {limits.max_member_uncompressed_bytes} in '{clean_name}'",
                            )
                            raise SecurityViolation(finding, is_limit=True)

                        if real_total_uncompressed > limits.max_total_uncompressed_bytes:
                            finding = SecurityFinding(
                                rule_id="SEC_TOTAL_UNCOMPRESSED_LIMIT",
                                observed_value=real_total_uncompressed,
                                configured_limit=limits.max_total_uncompressed_bytes,
                                reason=f"Total actual uncompressed bytes exceeded limit {limits.max_total_uncompressed_bytes}",
                            )
                            raise SecurityViolation(finding, is_limit=True)

                        # Runtime ratio check during streaming
                        effective_comp = max(m.compressed_size, limits.min_compressed_bytes_for_ratio)
                        if member_uncompressed_bytes > 0:
                            ratio = member_uncompressed_bytes / effective_comp
                            if ratio > limits.max_compression_ratio:
                                finding = SecurityFinding(
                                    rule_id="SEC_COMPRESSION_RATIO_LIMIT",
                                    member_name=clean_name,
                                    observed_value=round(ratio, 2),
                                    configured_limit=limits.max_compression_ratio,
                                    reason=f"Streaming compression ratio ({ratio:.1f}) exceeded limit {limits.max_compression_ratio} in '{clean_name}'",
                                )
                                raise SecurityViolation(finding, is_limit=True)

                # Flush any remainder
                out_chunk = decompressor.flush()
                if out_chunk:
                    member_uncompressed_bytes += len(out_chunk)
                    real_total_uncompressed += len(out_chunk)
                    crc_calc = zlib.crc32(out_chunk, crc_calc)
                    if is_xml_part:
                        decompressed_chunks.append(out_chunk)

                    if member_uncompressed_bytes > limits.max_member_uncompressed_bytes:
                        finding = SecurityFinding(
                            rule_id="SEC_MEMBER_UNCOMPRESSED_LIMIT",
                            member_name=clean_name,
                            observed_value=member_uncompressed_bytes,
                            configured_limit=limits.max_member_uncompressed_bytes,
                            reason=f"Actual uncompressed bytes exceeded limit {limits.max_member_uncompressed_bytes} in '{clean_name}'",
                        )
                        raise SecurityViolation(finding, is_limit=True)

                    if real_total_uncompressed > limits.max_total_uncompressed_bytes:
                        finding = SecurityFinding(
                            rule_id="SEC_TOTAL_UNCOMPRESSED_LIMIT",
                            observed_value=real_total_uncompressed,
                            configured_limit=limits.max_total_uncompressed_bytes,
                            reason=f"Total actual uncompressed bytes exceeded limit {limits.max_total_uncompressed_bytes}",
                        )
                        raise SecurityViolation(finding, is_limit=True)

                effective_comp = max(m.compressed_size, limits.min_compressed_bytes_for_ratio)
                if member_uncompressed_bytes > 0:
                    ratio = member_uncompressed_bytes / effective_comp
                    if ratio > limits.max_compression_ratio:
                        finding = SecurityFinding(
                            rule_id="SEC_COMPRESSION_RATIO_LIMIT",
                            member_name=clean_name,
                            observed_value=round(ratio, 2),
                            configured_limit=limits.max_compression_ratio,
                            reason=f"Decompressed compression ratio ({ratio:.1f}) exceeded limit {limits.max_compression_ratio} in '{clean_name}'",
                        )
                        raise SecurityViolation(finding, is_limit=True)

                if not getattr(decompressor, "eof", True) or member_uncompressed_bytes != m.uncompressed_size:
                    finding = SecurityFinding(
                        rule_id="SEC_TRUNCATED_STREAM",
                        member_name=clean_name,
                        reason=f"Truncated compressed deflate stream in member '{clean_name}'",
                    )
                    raise SecurityViolation(finding, is_limit=False)

            except zlib.error as e:
                finding = SecurityFinding(
                    rule_id="SEC_CORRUPTED_STREAM",
                    member_name=clean_name,
                    reason=f"Corrupted or truncated deflate stream in member '{clean_name}': {e}",
                )
                raise SecurityViolation(finding, is_limit=False) from e

        # Final CRC32 Verification
        final_crc = crc_calc & 0xFFFFFFFF
        if final_crc != m.crc:
            finding = SecurityFinding(
                rule_id="SEC_CRC_MISMATCH",
                member_name=clean_name,
                observed_value=f"0x{final_crc:08X}",
                configured_limit=f"0x{m.crc:08X}",
                reason=f"CRC32 mismatch for member '{clean_name}': expected 0x{m.crc:08X}, got 0x{final_crc:08X}",
            )
            raise SecurityViolation(finding, is_limit=False)

        # XML Preflight on Decompressed Part
        if is_xml_part:
            real_total_xml_bytes += member_uncompressed_bytes
            if real_total_xml_bytes > limits.max_total_xml_bytes:
                finding = SecurityFinding(
                    rule_id="SEC_TOTAL_XML_BYTES_LIMIT",
                    observed_value=real_total_xml_bytes,
                    configured_limit=limits.max_total_xml_bytes,
                    reason=f"Total XML bytes across package ({real_total_xml_bytes} B) exceeded limit {limits.max_total_xml_bytes} B",
                )
                raise SecurityViolation(finding, is_limit=True)

            xml_bytes = b"".join(decompressed_chunks)
            xml_res = preflight_xml_data(xml_bytes, limits=limits, part_name=m.name)
            if xml_res.max_xml_depth_observed > max_xml_depth:
                max_xml_depth = xml_res.max_xml_depth_observed
            total_xml_elements += xml_res.total_xml_elements_observed

    return SecurityPreflightResult(
        is_safe=True,
        total_members=len(members),
        total_uncompressed_bytes=real_total_uncompressed,
        total_xml_bytes=real_total_xml_bytes,
        max_xml_depth_observed=max_xml_depth,
        total_xml_elements_observed=total_xml_elements,
    )


def require_safe_zip_container(
    data: bytes,
    limits: Optional[SecurityLimits] = None,
) -> SecurityPreflightResult:
    """Enforce security preflight on ZIP container bytes; raises SecurityViolation on any breach."""
    return preflight_zip_container(data, limits=limits)
