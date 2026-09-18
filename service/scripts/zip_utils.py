"""Canonical ZIP utilities for ClearMark container parsers and validators."""

from __future__ import annotations

import struct


class ZipEocdError(Exception):
    """Exception raised when End of Central Directory (EOCD) cannot be safely located."""
    pass


def locate_zip_eocd(data: bytes) -> tuple[int, int, bytes]:
    """Locate the classic ZIP End of Central Directory (EOCD) record robustly.

    Algorithm invariants:
    - Minimum EOCD record length = 22 bytes
    - Maximum ZIP archive comment length = 65,535 bytes
    - Search window backwards from archive end: [len(data) - 65557, len(data) - 22]
    - Identify candidate signature b"PK\x05\x06" (0x06054b50)
    - Read 16-bit unsigned comment_length at offset +20
    - Accept candidate ONLY when: candidate_offset + 22 + comment_length == len(data)
    - If no candidate satisfies the exact archive boundary, fail closed.

    Returns:
        tuple of (eocd_offset, comment_length, raw_comment_bytes)

    Raises:
        ZipEocdError: if archive is too small, missing EOCD, or has boundary/comment mismatch.
    """
    data_len = len(data)
    if data_len < 22:
        raise ZipEocdError(f"Archive too small to contain valid EOCD ({data_len} B < 22 B)")

    # EOCD record is 22 bytes + comment up to 65535 bytes
    search_limit = min(data_len, 65557)
    start_pos = data_len - 22
    stop_pos = data_len - search_limit

    # Search backwards from archive end
    for i in range(start_pos, stop_pos - 1, -1):
        if data[i : i + 4] == b"PK\x05\x06":
            if i + 22 <= data_len:
                comment_len = struct.unpack("<H", data[i + 20 : i + 22])[0]
                if i + 22 + comment_len == data_len:
                    # Exact archive boundary invariant satisfied
                    comment_bytes = data[i + 22 : data_len]
                    return i, comment_len, comment_bytes

    # No candidate satisfied the exact archive boundary.
    # Distinguish missing EOCD vs trailing data or malformed comment length
    if b"PK\x05\x06" in data:
        raise ZipEocdError("Invalid ZIP archive: malformed EOCD comment length or trailing data after EOCD")
    raise ZipEocdError("Invalid ZIP archive: missing EOCD record")
