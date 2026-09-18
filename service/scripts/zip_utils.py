"""Canonical ZIP utilities for ClearMark container parsers and validators."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional


class ZipEocdError(Exception):
    """Exception raised when End of Central Directory (EOCD) cannot be safely located."""

    def __init__(self, message: str, rule_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.rule_id = rule_id


@dataclass(frozen=True, slots=True)
class ZipEocdInfo:
    """Immutable metadata about a validated ZIP End of Central Directory record."""

    offset: int
    comment_length: int
    comment: bytes
    disk_num: int
    cd_disk: int
    disk_entries: int
    total_entries: int
    cd_size: int
    cd_offset: int

    def __iter__(self):
        """Unpack as 3-tuple (offset, comment_length, comment) for backward compatibility."""
        return iter((self.offset, self.comment_length, self.comment))

    def __getitem__(self, idx):
        return (self.offset, self.comment_length, self.comment)[idx]

    def __len__(self):
        return 3

    def __eq__(self, other):
        if isinstance(other, tuple) and len(other) == 3:
            return (self.offset, self.comment_length, self.comment) == other
        if isinstance(other, ZipEocdInfo):
            return (
                self.offset == other.offset
                and self.comment_length == other.comment_length
                and self.comment == other.comment
                and self.disk_num == other.disk_num
                and self.cd_disk == other.cd_disk
                and self.disk_entries == other.disk_entries
                and self.total_entries == other.total_entries
                and self.cd_size == other.cd_size
                and self.cd_offset == other.cd_offset
            )
        return False



def _validate_eocd_candidate(
    data: bytes, candidate_offset: int, comment_len: int
) -> tuple[Optional[ZipEocdInfo], str, Optional[str]]:
    """Validate that an EOCD candidate record describes a structurally valid classic ZIP Central Directory.

    Required candidate validation for ClearMark's supported ZIP profile:
    - candidate record fits completely in buffer
    - disk_num == 0
    - cd_disk == 0
    - disk_entries == total_entries
    - reject classic ZIP64 sentinels (0xFFFF, 0xFFFFFFFF)
    - reject ZIP64 locator at structurally defined position (candidate_offset - 20)
    - cd_offset within bounds
    - cd_size within bounds
    - parse exactly total_entries Central Directory File Header records
    - every record starts with 0x02014B50
    - every variable-length filename/extra/comment block remains in bounds
    - reject ZIP64 extra fields (0x0001) in Central Directory and Local Headers
    - parse and validate referenced Local File Header records:
      * local_hdr_offset < cd_offset
      * local_hdr_offset + 30 <= len(data)
      * signature at local_hdr_offset == b"PK\x03\x04"
      * local filename and Central Directory filename are byte-identical
      * local compression method matches Central Directory method
      * relevant general-purpose flags are compatible (bit 0 encryption, bit 3 data descriptor)
      * local filename/extra lengths remain within archive bounds
      * local data start remains before Central Directory
      * for non-bit-3 entries, local data end remains before Central Directory
      * for bit-3 entries, do not require local CRC/size fields to equal CD values (deferred)
    - parsed Central Directory byte length == declared cd_size
    - parsed Central Directory end must reach the supported EOCD boundary:
      central_directory_end == candidate_offset

    Returns:
        tuple of (ZipEocdInfo | None, failure_reason, rule_id)
    """
    data_len = len(data)
    if candidate_offset + 22 + comment_len != data_len:
        return None, "Candidate does not match archive boundary", "SEC_TRUNCATED_EOCD"

    sig, disk_num, cd_disk, disk_entries, total_entries, cd_size, cd_offset, decl_comment_len = struct.unpack(
        "<4sHHHHIIH", data[candidate_offset : candidate_offset + 22]
    )
    if sig != b"PK\x05\x06" or decl_comment_len != comment_len:
        return None, "Invalid EOCD signature or declared comment length", "SEC_TRUNCATED_EOCD"

    # Multi-disk archive check
    if disk_num != 0 or cd_disk != 0:
        return (
            None,
            f"Multi-disk ZIP archives are unsupported (disk {disk_num}, cd_disk {cd_disk})",
            "SEC_MULTIDISK_ARCHIVE",
        )

    # Fail closed on classic ZIP64 sentinels
    if (
        disk_num == 0xFFFF
        or cd_disk == 0xFFFF
        or disk_entries == 0xFFFF
        or total_entries == 0xFFFF
        or cd_size == 0xFFFFFFFF
        or cd_offset == 0xFFFFFFFF
    ):
        return None, "ZIP64 container structures are unsupported fail-closed", "SEC_ZIP64_UNSUPPORTED"

    # Fail closed on ZIP64 locator at its structurally defined position immediately before EOCD
    if candidate_offset >= 20 and data[candidate_offset - 20 : candidate_offset - 16] == b"PK\x06\x07":
        return None, "ZIP64 locator structure preceding EOCD record", "SEC_ZIP64_UNSUPPORTED"

    # Disk entries must match total entries for single-disk profile
    if disk_entries != total_entries:
        return (
            None,
            f"Disk entry count ({disk_entries}) does not match total entry count ({total_entries})",
            "SEC_ENTRY_COUNT_MISMATCH",
        )

    # Bounds validation
    if cd_offset < 0 or cd_offset > data_len:
        return (
            None,
            f"Central directory offset {cd_offset} outside archive bounds ({data_len} B)",
            "SEC_BAD_CD_OFFSET",
        )

    if cd_offset + cd_size > candidate_offset or cd_offset + cd_size > data_len:
        return (
            None,
            "Central directory extends beyond EOCD or archive boundary",
            "SEC_TRUNCATED_CD",
        )

    # Parsed Central Directory end must reach the supported EOCD boundary:
    # central_directory_end == candidate_offset
    if cd_offset + cd_size != candidate_offset:
        return (
            None,
            f"Central directory end ({cd_offset + cd_size}) does not match EOCD boundary ({candidate_offset})",
            "SEC_TRUNCATED_CD",
        )

    cd_end = candidate_offset
    curr = cd_offset

    # Parse exactly total_entries Central Directory File Header records
    for _ in range(total_entries):
        if curr + 46 > cd_end:
            return None, f"Truncated Central Directory record at offset {curr}", "SEC_TRUNCATED_CD_RECORD"
        if data[curr : curr + 4] != b"PK\x01\x02":
            return None, f"Invalid Central Directory record signature at offset {curr}", "SEC_TRUNCATED_CD_RECORD"

        (
            cd_sig,
            cd_made_by,
            cd_ver,
            cd_flags,
            cd_comp,
            cd_mtime,
            cd_mdate,
            cd_crc,
            cd_csize,
            cd_usize,
            cd_fn_len,
            cd_extra_len,
            cd_comment_len,
            disk_num_start,
            cd_iattr,
            cd_eattr,
            local_hdr_offset,
        ) = struct.unpack("<IHHHHHHIIIHHHHHII", data[curr : curr + 46])

        # Multi-disk or ZIP64 disk start is invalid for single-disk profile
        if disk_num_start != 0:
            return None, f"Multi-disk central directory entry at offset {curr}", "SEC_MULTIDISK_ARCHIVE"

        # Check compressed/uncompressed sizes and offset for ZIP64 sentinels
        if cd_csize == 0xFFFFFFFF or cd_usize == 0xFFFFFFFF or local_hdr_offset == 0xFFFFFFFF:
            return None, "ZIP64 extra field sentinel in Central Directory record", "SEC_ZIP64_UNSUPPORTED"

        rec_len = 46 + cd_fn_len + cd_extra_len + cd_comment_len
        if curr + rec_len > cd_end:
            return None, f"Truncated Central Directory record at offset {curr}", "SEC_TRUNCATED_CD_RECORD"

        cd_name = data[curr + 46 : curr + 46 + cd_fn_len]

        # ----------------------------------------------------------------------
        # Local Header Reference Validation
        # ----------------------------------------------------------------------
        if local_hdr_offset < 0 or local_hdr_offset >= cd_offset:
            return (
                None,
                f"Local header offset {local_hdr_offset} not before Central Directory ({cd_offset})",
                "SEC_BAD_LOCAL_HEADER_OFFSET",
            )

        if local_hdr_offset + 30 > data_len:
            return (
                None,
                f"Local header at {local_hdr_offset} extends beyond archive bounds ({data_len} B)",
                "SEC_BAD_LOCAL_HEADER_BOUNDS",
            )

        if data[local_hdr_offset : local_hdr_offset + 4] != b"PK\x03\x04":
            return (
                None,
                f"Invalid Local File Header signature at offset {local_hdr_offset}",
                "SEC_INVALID_LOCAL_SIGNATURE",
            )

        (
            loc_sig,
            loc_ver,
            loc_flags,
            loc_comp,
            loc_mtime,
            loc_mdate,
            loc_crc,
            loc_csize,
            loc_usize,
            loc_fn_len,
            loc_extra_len,
        ) = struct.unpack("<IHHHHHIIIHH", data[local_hdr_offset : local_hdr_offset + 30])

        loc_hdr_len = 30 + loc_fn_len + loc_extra_len
        if local_hdr_offset + loc_hdr_len > data_len:
            return (
                None,
                f"Local header at {local_hdr_offset} extends beyond archive bounds ({data_len} B)",
                "SEC_BAD_LOCAL_HEADER_BOUNDS",
            )

        loc_name = data[local_hdr_offset + 30 : local_hdr_offset + 30 + loc_fn_len]
        if loc_name != cd_name:
            return (
                None,
                "Local header filename does not match Central Directory entry",
                "SEC_LOCAL_CENTRAL_MISMATCH",
            )

        if loc_comp != cd_comp:
            return (
                None,
                f"Local compression method ({loc_comp}) does not match Central Directory ({cd_comp})",
                "SEC_LOCAL_CENTRAL_MISMATCH",
            )

        # Relevant general purpose flags compatible (bit 0 encryption, bit 3 data descriptor)
        if (loc_flags & 0x0001) != (cd_flags & 0x0001):
            return None, "Local header encryption flag mismatch", "SEC_LOCAL_CENTRAL_MISMATCH"

        if (loc_flags & 0x0008) != (cd_flags & 0x0008):
            return None, "Local header bit-3 data descriptor flag mismatch", "SEC_LOCAL_CENTRAL_MISMATCH"

        data_start = local_hdr_offset + loc_hdr_len
        if data_start > cd_offset:
            return (
                None,
                f"Local member data start ({data_start}) extends into Central Directory ({cd_offset})",
                "SEC_OVERLAPPING_MEMBERS",
            )

        # For non-bit-3 entries, verify payload does not overlap into Central Directory
        if not (cd_flags & 0x0008):
            if data_start + cd_csize > cd_offset:
                return (
                    None,
                    f"Local member payload end ({data_start + cd_csize}) extends into Central Directory ({cd_offset})",
                    "SEC_OVERLAPPING_MEMBERS",
                )

        curr += rec_len

    # Parsed Central Directory byte length == declared cd_size
    if curr != cd_end:
        return None, "Parsed Central Directory byte length does not match declared cd_size", "SEC_TRUNCATED_CD"

    comment_bytes = data[candidate_offset + 22 : data_len]
    return (
        ZipEocdInfo(
            offset=candidate_offset,
            comment_length=comment_len,
            comment=comment_bytes,
            disk_num=disk_num,
            cd_disk=cd_disk,
            disk_entries=disk_entries,
            total_entries=total_entries,
            cd_size=cd_size,
            cd_offset=cd_offset,
        ),
        "",
        None,
    )


def locate_zip_eocd(data: bytes) -> ZipEocdInfo:
    """Locate the classic ZIP End of Central Directory (EOCD) record robustly.

    Algorithm invariants:
    - Minimum EOCD record length = 22 bytes
    - Maximum ZIP archive comment length = 65,535 bytes
    - Search window backwards from archive end: [len(data) - 65557, len(data) - 22]
    - Identify candidate signature b"PK\x05\x06" (0x06054b50)
    - Read 16-bit unsigned comment_length at offset +20
    - Check candidate exact archive boundary: candidate_offset + 22 + comment_length == len(data)
    - Validate candidate Central Directory and Local Header structural integrity (_validate_eocd_candidate)
    - Scan the entire window and collect all candidates satisfying boundary and structural validation.
    - If exactly 1 structurally valid candidate exists: ACCEPT.
    - If > 1 structurally valid candidates exist: FAIL CLOSED with SEC_AMBIGUOUS_EOCD.
    - If 0 valid candidates exist: FAIL CLOSED with diagnostic from earliest candidate or boundary mismatch.

    Returns:
        ZipEocdInfo with offset, comment_length, comment, disk_num, cd_disk, disk_entries,
        total_entries, cd_size, cd_offset. Unpacks as 3-tuple (offset, comment_length, comment).

    Raises:
        ZipEocdError: if archive is too small, missing EOCD, structurally invalid, or ambiguous.
    """
    data_len = len(data)
    if data_len < 22:
        raise ZipEocdError(
            f"Archive too small to contain valid EOCD ({data_len} B < 22 B)",
            rule_id="SEC_TRUNCATED_ARCHIVE",
        )

    # EOCD record is 22 bytes + comment up to 65535 bytes
    search_limit = min(data_len, 65557)
    start_pos = data_len - 22
    stop_pos = data_len - search_limit

    valid_candidates: list[ZipEocdInfo] = []
    invalid_candidates: list[tuple[int, str, Optional[str]]] = []

    # Search backwards from archive end
    for i in range(start_pos, stop_pos - 1, -1):
        if data[i : i + 4] == b"PK\x05\x06":
            if i + 22 <= data_len:
                comment_len = struct.unpack("<H", data[i + 20 : i + 22])[0]
                if i + 22 + comment_len == data_len:
                    # Candidate satisfies boundary invariant; validate CD & Local structure
                    candidate_info, reason, rule_id = _validate_eocd_candidate(data, i, comment_len)
                    if candidate_info is not None:
                        valid_candidates.append(candidate_info)
                    else:
                        invalid_candidates.append((i, reason, rule_id))

    # Single valid candidate: unambiguous classic ZIP
    if len(valid_candidates) == 1:
        return valid_candidates[0]

    # Multiple structurally valid candidates: fail closed on ambiguity
    if len(valid_candidates) > 1:
        raise ZipEocdError(
            "Multiple structurally valid EOCD interpretations exist",
            rule_id="SEC_AMBIGUOUS_EOCD",
        )

    # Zero valid candidates: fail closed
    if invalid_candidates:
        # Pick the candidate closest to Central Directory (smallest offset; last in backward scan)
        earliest_offset, earliest_reason, earliest_rule_id = invalid_candidates[-1]
        raise ZipEocdError(
            f"Invalid ZIP archive: EOCD candidate at offset {earliest_offset} failed structural validation: {earliest_reason}",
            rule_id=earliest_rule_id,
        )

    if b"PK\x05\x06" in data:
        raise ZipEocdError(
            "Invalid ZIP archive: malformed EOCD comment length or trailing data after EOCD",
            rule_id="SEC_TRUNCATED_EOCD",
        )
    raise ZipEocdError(
        "Invalid ZIP archive: missing EOCD record",
        rule_id="SEC_MISSING_EOCD",
    )
