"""Format-native OPC package layer for lossless PPTX processing."""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile
from pathlib import Path
from typing import Optional

from .exceptions import (
    PptxCorruptedPackageError,
    PptxSecurityLimitError,
    PptxUnsupportedFeatureError,
)

MAX_UNCOMPRESSED_BUDGET = 128 * 1024 * 1024  # 128 MiB
MAX_COMPRESSION_RATIO = 100


class PptxPackage:
    """Read and manipulate Open Packaging Conventions (OPC) PPTX archives."""

    def __init__(self, data: bytes):
        if not data.startswith(b"PK\x03\x04") and not data.startswith(b"PK\x05\x06"):
            raise PptxCorruptedPackageError("File does not start with standard ZIP magic bytes.")

        self.raw_data = data
        self.member_order: list[str] = []
        self._members: dict[str, bytes] = {}
        self.hashes: dict[str, str] = {}
        self._zip_infos: dict[str, zipfile.ZipInfo] = {}
        self._raw_local_records: dict[str, bytes] = {}
        self._compressed_payloads: dict[str, bytes] = {}
        self.raw_compressed_hashes: dict[str, str] = {}
        self._central_directory_records: dict[str, bytes] = {}
        self._parse_package()

    def _parse_package(self) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(self.raw_data), "r") as zf:
                total_uncompressed = 0
                seen_names: set[str] = set()

                for info in zf.infolist():
                    name = info.filename
                    if name in seen_names:
                        raise PptxCorruptedPackageError(f"Duplicate archive member detected: {name}")
                    seen_names.append(name) if hasattr(seen_names, "append") else seen_names.add(name)

                    # Path traversal safety check
                    norm_path = Path(name)
                    if norm_path.is_absolute() or ".." in norm_path.parts:
                        raise PptxSecurityLimitError(f"Unsafe path traversal member detected: {name}")

                    # Macro / Digital signature detection
                    if "vbaProject.bin" in name.lower():
                        raise PptxUnsupportedFeatureError("Macro-enabled PPTX (.pptm) or embedded VBA is unsupported.")
                    if name.startswith("_xmlsignatures/") or name.endswith(".vsa"):
                        raise PptxUnsupportedFeatureError("Digitally signed PPTX presentation is unsupported for mutation.")

                    # Decompression ratio check
                    if info.compress_size > 0:
                        ratio = info.file_size / info.compress_size
                        if ratio > MAX_COMPRESSION_RATIO and info.file_size > 1024 * 1024:
                            raise PptxSecurityLimitError(
                                f"Decompression ratio ({ratio:.1f}) exceeds security limit on member: {name}"
                            )

                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_UNCOMPRESSED_BUDGET:
                        raise PptxSecurityLimitError(
                            f"Total uncompressed package size exceeds {MAX_UNCOMPRESSED_BUDGET} bytes budget."
                        )

                    self.member_order.append(name)
                    self._zip_infos[name] = info
                    raw_member = zf.read(name)
                    self._members[name] = raw_member
                    self.hashes[name] = hashlib.sha256(raw_member).hexdigest()

            self._parse_raw_records()

            # PresentationML sanity verification
            if "ppt/presentation.xml" not in self._members and not any(n.startswith("ppt/") for n in self._members):
                raise PptxCorruptedPackageError("Missing ppt/presentation.xml or ppt/ structure in archive.")

        except (zipfile.BadZipFile, struct.error) as e:
            raise PptxCorruptedPackageError(f"Malformed or corrupt ZIP archive: {e}") from e

    def _parse_raw_records(self) -> None:
        """Extract exact local headers, compressed streams, and central directory records."""
        data = self.raw_data
        pos = 0
        total_len = len(data)
        local_offsets: dict[str, int] = {}

        while pos < total_len - 4:
            sig = data[pos : pos + 4]
            if sig == b"PK\x03\x04":  # Local file header
                try:
                    (
                        version_needed,
                        flags,
                        compression,
                        mod_time,
                        mod_date,
                        crc,
                        comp_size,
                        uncomp_size,
                        fn_len,
                        extra_len,
                    ) = struct.unpack("<HHHHHIIIHH", data[pos + 4 : pos + 30])
                    header_len = 30 + fn_len + extra_len
                    fn_bytes = data[pos + 30 : pos + 30 + fn_len]
                    fn_str = fn_bytes.decode("utf-8", errors="replace")

                    local_header_bytes = data[pos : pos + header_len]
                    # A11: Data descriptor handling if bit 3 is set
                    desc_len = 0
                    if flags & 0x08:
                        cand = data[pos + header_len + comp_size : pos + header_len + comp_size + 16]
                        desc_len = 16 if cand.startswith(b"PK\x07\x08") else 12

                    payload = data[pos + header_len : pos + header_len + comp_size]
                    full_payload_with_desc = data[pos + header_len : pos + header_len + comp_size + desc_len]

                    self._raw_local_records[fn_str] = local_header_bytes
                    self._compressed_payloads[fn_str] = full_payload_with_desc
                    self.raw_compressed_hashes[fn_str] = hashlib.sha256(payload).hexdigest()
                    local_offsets[fn_str] = pos

                    pos += header_len + comp_size + desc_len
                except Exception:
                    break
            elif sig == b"PK\x01\x02":  # Central directory header
                try:
                    (
                        ver_made,
                        ver_need,
                        flags,
                        comp,
                        mod_time,
                        mod_date,
                        crc,
                        comp_size,
                        uncomp_size,
                        fn_len,
                        extra_len,
                        comment_len,
                        disk_num,
                        int_attr,
                        ext_attr,
                        rel_offset,
                    ) = struct.unpack("<HHHHHHIIIHHHHHII", data[pos + 4 : pos + 46])
                    total_cd_len = 46 + fn_len + extra_len + comment_len
                    fn_bytes = data[pos + 46 : pos + 46 + fn_len]
                    fn_str = fn_bytes.decode("utf-8", errors="replace")

                    self._central_directory_records[fn_str] = data[pos : pos + total_cd_len]
                    pos += total_cd_len
                except Exception:
                    break
            else:
                pos += 1

    @property
    def zip_infos(self) -> dict[str, zipfile.ZipInfo]:
        return self._zip_infos

    def has_member(self, name: str) -> bool:
        return name in self._members

    def get_member(self, name: str) -> Optional[bytes]:
        return self._members.get(name)

    def get_hash(self, name: str) -> Optional[str]:
        return self.hashes.get(name)

    def get_member_info(self, name: str) -> Optional[zipfile.ZipInfo]:
        return self._zip_infos.get(name)

    def get_raw_local_record(self, name: str) -> Optional[bytes]:
        return self._raw_local_records.get(name)

    def get_local_record(self, name: str) -> Optional[bytes]:
        return self._raw_local_records.get(name)

    def get_compressed_payload(self, name: str) -> Optional[bytes]:
        return self._compressed_payloads.get(name)

    def get_compressed_hash(self, name: str) -> Optional[str]:
        return self.raw_compressed_hashes.get(name)

    def get_central_directory_record(self, name: str) -> Optional[bytes]:
        return self._central_directory_records.get(name)

    def rebuild(
        self,
        patched_members: dict[str, bytes],
        dropped_members: Optional[set[str]] = None,
    ) -> bytes:
        """Rebuild the ZIP package with strict raw non-target entry pass-through."""
        return self.build_patched_package(patched_members, dropped_members)

    def build_patched_package(
        self,
        patched_members: dict[str, bytes],
        dropped_members: Optional[set[str]] = None,
    ) -> bytes:
        """Construct a new PPTX container with strict raw OPC passthrough for non-target parts."""
        dropped = dropped_members or set()
        out = io.BytesIO()
        new_local_offsets: dict[str, int] = {}
        new_cd_records: list[bytes] = []

        for name in self.member_order:
            if name in dropped:
                continue

            current_offset = out.tell()
            new_local_offsets[name] = current_offset

            if name in patched_members:
                # Target modified part: compress and emit
                new_payload = patched_members[name]
                crc = zipfile.crc32(new_payload)
                uncomp_size = len(new_payload)

                import zlib
                comp_obj = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
                comp_payload = comp_obj.compress(new_payload) + comp_obj.flush()
                comp_size = len(comp_payload)

                fn_bytes = name.encode("utf-8")
                fn_len = len(fn_bytes)

                local_header = struct.pack(
                    "<4sHHHHHIIIHH",
                    b"PK\x03\x04",
                    20,     # Version needed
                    2048,   # General purpose bit flag (UTF-8)
                    8,      # Compression method (DEFLATED)
                    0, 0,   # Timestamp
                    crc,
                    comp_size,
                    uncomp_size,
                    fn_len,
                    0,      # Extra field length
                ) + fn_bytes

                out.write(local_header)
                out.write(comp_payload)

                # Construct updated central directory record
                cd_record = struct.pack(
                    "<4sHHHHHHIIIHHHHHII",
                    b"PK\x01\x02",
                    63,     # Version made by
                    20,     # Version needed
                    2048,   # Flags (UTF-8)
                    8,      # Compression
                    0, 0,   # Timestamp
                    crc,
                    comp_size,
                    uncomp_size,
                    fn_len,
                    0,      # Extra field length
                    0,      # Comment length
                    0, 0, 0,
                    current_offset,
                ) + fn_bytes
                new_cd_records.append(cd_record)
            else:
                # Non-target part: STRICT RAW OPC PASSTHROUGH
                orig_local = self._raw_local_records.get(name)
                orig_comp = self._compressed_payloads.get(name)
                orig_cd = self._central_directory_records.get(name)

                if orig_local is not None and orig_comp is not None and orig_cd is not None:
                    out.write(orig_local)
                    out.write(orig_comp)

                    # Update only relative local header offset (bytes 42..46) in central directory
                    updated_cd = orig_cd[:42] + struct.pack("<I", current_offset) + orig_cd[46:]
                    new_cd_records.append(updated_cd)
                else:
                    # Fallback if raw slice unavailable
                    raw = self._members[name]
                    zinfo = self._zip_infos.get(name)
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf_tmp:
                        zf_tmp.writestr(name, raw)
                    raw_zip = buf.getvalue()
                    out.write(raw_zip)

        # Write Central Directory
        cd_start_offset = out.tell()
        for cd_rec in new_cd_records:
            out.write(cd_rec)
        cd_size = out.tell() - cd_start_offset
        total_entries = len(new_cd_records)

        # Write End of Central Directory Record (EOCD)
        eocd = struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",
            0,      # Disk number
            0,      # Disk with CD
            total_entries,
            total_entries,
            cd_size,
            cd_start_offset,
            0,      # Comment length
        )
        out.write(eocd)

        return out.getvalue()
