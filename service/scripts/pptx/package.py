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


def _filter_rebuild_incompatible_extra_fields(extra: bytes, exc_cls: type[Exception]) -> bytes:
    """Preserve original extra fields except entries proven incompatible with rewriting the member.

    Container fidelity policy:
    Retains unknown, non-prohibited extra fields (e.g. 0x5455 extended timestamp, 0x7875 unix UID/GID,
    or proprietary vendor blocks) byte-for-byte on rewritten members to preserve container metadata.
    Strips entries that are proven incompatible with member rewriting:
    - 0x0001 (Zip64): contains stale uncompressed/compressed sizes and offsets for the pre-rewrite stream.
      Must be stripped when re-encoding 32-bit content to avoid size/offset corruption.
    - 0xA220 (MS Open Packaging Growth Hint): pre-allocation padding tailored to original stream length,
      obsolete upon rewriting.
    Does not claim preserved unknown fields are independently proven safe; container security preflight
    remains responsible for rejecting unsupported or dangerous container structures.

    Fails closed on truncated or malformed extra fields.
    """
    if not extra:
        return b""
    retained_chunks: list[bytes] = []
    idx = 0
    total = len(extra)
    while idx + 4 <= total:
        header_id, data_size = struct.unpack_from("<HH", extra, idx)
        block_len = 4 + data_size
        if idx + block_len > total:
            raise exc_cls(f"Malformed ZIP extra field: block truncated at offset {idx}")
        # Strip entries incompatible with rewriting the member
        if header_id not in (0x0001, 0xA220):
            retained_chunks.append(extra[idx : idx + block_len])
        idx += block_len
    if idx != total:
        raise exc_cls(f"Trailing bytes in ZIP extra field: {total - idx} bytes")
    return b"".join(retained_chunks)


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
        self._raw_local_extra: dict[str, bytes] = {}
        self._raw_cd_extra: dict[str, bytes] = {}
        self._raw_cd_comment: dict[str, bytes] = {}
        self._raw_disk_number_start: dict[str, int] = {}
        self._raw_eocd_comment: bytes = b""
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
        """Extract exact local headers, compressed streams, and central directory records using Central Directory."""
        data = self.raw_data
        eocd_idx = data.rfind(b"PK\x05\x06")
        if eocd_idx == -1:
            raise PptxCorruptedPackageError("Invalid PPTX package: missing EOCD record")

        (
            disk_num,
            cd_disk,
            disk_entries,
            total_entries,
            cd_size,
            cd_offset,
            comment_len,
        ) = struct.unpack("<HHHHIIH", data[eocd_idx + 4 : eocd_idx + 22])

        if eocd_idx + 22 + comment_len > len(data):
            raise PptxCorruptedPackageError(
                f"Invalid PPTX package: malformed EOCD comment length ({comment_len} exceeds package bounds)"
            )
        self._raw_eocd_comment = data[eocd_idx + 22 : eocd_idx + 22 + comment_len]

        if total_entries != len(self.member_order):
            raise PptxCorruptedPackageError("ZIP entry count mismatch between Central Directory and ZipFile")

        cd_pos = cd_offset
        self._raw_mtime: dict[str, int] = {}
        self._raw_mdate: dict[str, int] = {}

        for _ in range(total_entries):
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
                raise PptxCorruptedPackageError(f"Invalid Central Directory record signature at offset {cd_pos}")

            name = data[cd_pos + 46 : cd_pos + 46 + nlen].decode("utf-8", errors="replace")
            rec_len = 46 + nlen + elen + clen
            self._central_directory_records[name] = data[cd_pos : cd_pos + rec_len]
            self._raw_mtime[name] = mtime
            self._raw_mdate[name] = mdate
            self._raw_cd_extra[name] = data[cd_pos + 46 + nlen : cd_pos + 46 + nlen + elen]
            self._raw_cd_comment[name] = data[cd_pos + 46 + nlen + elen : cd_pos + 46 + nlen + elen + clen]
            self._raw_disk_number_start[name] = dnum
            cd_pos += rec_len

            # Read Local File Header from lhoff
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
                raise PptxCorruptedPackageError(f"Invalid Local File Header signature for '{name}' at offset {lhoff}")

            self._raw_local_extra[name] = data[lhoff + 30 + lnlen : lhoff + 30 + lnlen + lelen]

            loc_hdr_len = 30 + lnlen + lelen
            # csize from Central Directory is authoritative even if lcsize == 0 due to bit 3
            raw_comp_payload = data[lhoff + loc_hdr_len : lhoff + loc_hdr_len + csize]
            self.raw_compressed_hashes[name] = hashlib.sha256(raw_comp_payload).hexdigest()

            # Data descriptor handling if lflags & 0x08
            desc_len = 0
            if lflags & 0x08:
                cand = data[lhoff + loc_hdr_len + csize : lhoff + loc_hdr_len + csize + 16]
                desc_len = 16 if cand.startswith(b"PK\x07\x08") else 12

            total_local_len = loc_hdr_len + csize + desc_len
            self._raw_local_records[name] = data[lhoff : lhoff + total_local_len]
            self._compressed_payloads[name] = raw_comp_payload

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
        patched_members: dict[str, bytes] | None = None,
        dropped_members: Optional[set[str]] = None,
        *,
        changed_parts: dict[str, bytes] | None = None,
        dropped_parts: Optional[set[str]] = None,
    ) -> bytes:
        """Rebuild the ZIP package with strict raw non-target entry pass-through."""
        changes = patched_members if patched_members is not None else (changed_parts or {})
        drops = dropped_members if dropped_members is not None else dropped_parts
        return self.build_patched_package(changes, drops)

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
                # Target modified part: compress and emit with compatible source metadata
                new_payload = patched_members[name]
                orig_info = self._zip_infos.get(name)

                import zlib
                if orig_info and orig_info.compress_type == zipfile.ZIP_STORED:
                    comp_payload = new_payload
                    comp_type = zipfile.ZIP_STORED
                else:
                    comp_obj = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
                    comp_payload = comp_obj.compress(new_payload) + comp_obj.flush()
                    comp_type = zipfile.ZIP_DEFLATED

                crc = zlib.crc32(new_payload) & 0xFFFFFFFF
                uncomp_size = len(new_payload)
                comp_size = len(comp_payload)

                fn_bytes = name.encode("utf-8")
                fn_len = len(fn_bytes)

                mtime = self._raw_mtime.get(name, 0)
                mdate = self._raw_mdate.get(name, 0x21)

                orig_flags = orig_info.flag_bits if orig_info else 0
                # A11: Clear bit 3 (data descriptor) on modified entry as exact CRC/sizes are in header
                new_flag_bits = orig_flags & ~0x08
                extract_ver = orig_info.extract_version if orig_info else 20
                create_ver = orig_info.create_version if orig_info else 20
                int_attr = orig_info.internal_attr if orig_info else 0
                ext_attr = orig_info.external_attr if orig_info else 0

                # Extra fields and comment preservation (A11)
                safe_local_extra = _filter_rebuild_incompatible_extra_fields(
                    self._raw_local_extra.get(name, b""), PptxCorruptedPackageError
                )
                safe_cd_extra = _filter_rebuild_incompatible_extra_fields(
                    self._raw_cd_extra.get(name, b""), PptxCorruptedPackageError
                )
                orig_comment = self._raw_cd_comment.get(name, b"")
                dnum = self._raw_disk_number_start.get(name, 0)

                local_header = struct.pack(
                    "<IHHHHHIIIHH",
                    0x04034B50,
                    extract_ver,
                    new_flag_bits,
                    comp_type,
                    mtime,
                    mdate,
                    crc,
                    comp_size,
                    uncomp_size,
                    fn_len,
                    len(safe_local_extra),
                ) + fn_bytes + safe_local_extra

                out.write(local_header)
                out.write(comp_payload)

                # Construct updated central directory record preserving source metadata
                cd_record = struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,
                    create_ver,
                    extract_ver,
                    new_flag_bits,
                    comp_type,
                    mtime,
                    mdate,
                    crc,
                    comp_size,
                    uncomp_size,
                    fn_len,
                    len(safe_cd_extra),
                    len(orig_comment),
                    dnum,
                    int_attr,
                    ext_attr,
                    current_offset,
                ) + fn_bytes + safe_cd_extra + orig_comment
                new_cd_records.append(cd_record)
            else:
                # Non-target part: STRICT RAW OPC PASSTHROUGH
                orig_local = self._raw_local_records.get(name)
                orig_cd = self._central_directory_records.get(name)

                if orig_local is not None and orig_cd is not None:
                    # orig_local contains full entry: local header + compressed payload + descriptor
                    out.write(orig_local)

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

        # Write End of Central Directory Record (EOCD) with preserved archive-level comment (A11)
        eocd_comment = self._raw_eocd_comment
        eocd = struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",
            0,      # Disk number
            0,      # Disk with CD
            total_entries,
            total_entries,
            cd_size,
            cd_start_offset,
            len(eocd_comment), # Comment length
        )
        out.write(eocd)
        if eocd_comment:
            out.write(eocd_comment)

        return out.getvalue()
