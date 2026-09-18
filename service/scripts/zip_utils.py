"""Canonical ZIP utilities for ClearMark container parsers and validators."""

from __future__ import annotations

import struct


class ZipEocdError(Exception):
    """Exception raised when End of Central Directory (EOCD) cannot be safely located."""

    def __init__(self, message: str, rule_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.rule_id = rule_id


class ZipEocdInfo:
    """Immutable metadata about a validated ZIP End of Central Directory record."""

    __slots__ = (
        "offset",
        "comment_length",
        "comment",
        "disk_num",
        "cd_disk",
        "disk_entries",
        "total_entries",
        "cd_size",
        "cd_offset",
    )

    def __init__(
        self,
        offset: int,
        comment_length: int,
        comment: bytes,
        disk_num: int,
        cd_disk: int,
        disk_entries: int,
        total_entries: int,
        cd_size: int,
        cd_offset: int,
    ) -> None:
        self.offset = offset
        self.comment_length = comment_length
        self.comment = comment
        self.disk_num = disk_num
        self.cd_disk = cd_disk
        self.disk_entries = disk_entries
        self.total_entries = total_entries
        self.cd_size = cd_size
        self.cd_offset = cd_offset

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

    def __repr__(self) -> str:
        return (
            f"ZipEocdInfo(offset={self.offset}, comment_length={self.comment_length}, "
            f"total_entries={self.total_entries}, cd_size={self.cd_size}, cd_offset={self.cd_offset})"
        )


def _validate_eocd_candidate(
    data: bytes, candidate_offset: int, comment_len: int
) -> tuple[Optional[ZipEocdInfo], str, Optional[str]]:
    """Validate that an EOCD candidate record describes a structurally valid classic ZIP Central Directory.

    Required candidate validation for ClearMark's supported ZIP profile:
    - candidate record fits completely in buffer
    - disk_num == 0
    - cd_disk == 0
    - disk_entries == total_entries
    - reject ZIP64 sentinels according to existing fail-closed policy
    - cd_offset within bounds
    - cd_size within bounds
    - parse exactly total_entries Central Directory File Header records
    - every record starts with 0x02014B50
    - every variable-length filename/extra/comment block remains in bounds
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

    # Fail closed on ZIP64 sentinels or presence of ZIP64 directory locator/end
    if (
        disk_num == 0xFFFF
        or cd_disk == 0xFFFF
        or disk_entries == 0xFFFF
        or total_entries == 0xFFFF
        or cd_size == 0xFFFFFFFF
        or cd_offset == 0xFFFFFFFF
        or b"PK\x06\x07" in data
        or b"PK\x06\x06" in data
    ):
        return None, "ZIP64 container structures are unsupported fail-closed", "SEC_ZIP64_UNSUPPORTED"

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
            fn_len,
            extra_len,
            comment_len_entry,
            disk_num_start,
        ) = struct.unpack("<HHHH", data[curr + 28 : curr + 36])

        # Multi-disk or ZIP64 disk start is invalid for single-disk profile
        if disk_num_start != 0:
            return None, f"Multi-disk central directory entry at offset {curr}", "SEC_MULTIDISK_ARCHIVE"

        # Check compressed/uncompressed sizes for ZIP64 sentinels
        comp_size, uncomp_size = struct.unpack("<II", data[curr + 20 : curr + 28])
        local_hdr_offset = struct.unpack("<I", data[curr + 42 : curr + 46])[0]
        if comp_size == 0xFFFFFFFF or uncomp_size == 0xFFFFFFFF or local_hdr_offset == 0xFFFFFFFF:
            return None, "ZIP64 extra field sentinel in Central Directory record", "SEC_ZIP64_UNSUPPORTED"

        record_len = 46 + fn_len + extra_len + comment_len_entry
        if curr + record_len > cd_end:
            return None, f"Truncated Central Directory record at offset {curr}", "SEC_TRUNCATED_CD_RECORD"
        curr += record_len

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
    - Validate candidate Central Directory structural integrity (_validate_eocd_candidate)
    - If a candidate matches the boundary but fails structural validation, continue scanning backwards
      (as the candidate may be embedded within a legitimate archive comment).
    - If no candidate satisfies both boundary and structural validation, fail closed.

    Returns:
        ZipEocdInfo with offset, comment_length, comment, disk_num, cd_disk, disk_entries,
        total_entries, cd_size, cd_offset. Unpacks as 3-tuple (offset, comment_length, comment).

    Raises:
        ZipEocdError: if archive is too small, missing EOCD, or has structural/boundary corruption.
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

    candidates_checked: list[tuple[int, str, Optional[str]]] = []

    # Search backwards from archive end
    for i in range(start_pos, stop_pos - 1, -1):
        if data[i : i + 4] == b"PK\x05\x06":
            if i + 22 <= data_len:
                comment_len = struct.unpack("<H", data[i + 20 : i + 22])[0]
                if i + 22 + comment_len == data_len:
                    # Candidate satisfies boundary invariant; validate CD structure
                    candidate_info, reason, rule_id = _validate_eocd_candidate(data, i, comment_len)
                    if candidate_info is not None:
                        return candidate_info
                    # Candidate failed structural validation — continue scanning backwards
                    # to see if an earlier candidate is the real EOCD record.
                    candidates_checked.append((i, reason, rule_id))

    # No candidate satisfied both archive boundary and structural validation.
    if candidates_checked:
        # Pick the candidate closest to Central Directory (smallest offset; last in backward scan)
        earliest_offset, earliest_reason, earliest_rule_id = candidates_checked[-1]
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
