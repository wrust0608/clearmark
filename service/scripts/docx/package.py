"""OPC ZIP package manager for DOCX files with strict raw non-target pass-through."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import struct
import zipfile
import zlib

try:
    from .exceptions import DocxFidelityException
except (ImportError, ValueError):
    from docx.exceptions import DocxFidelityException

MAX_DOCX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024  # 128 MB max uncompressed package
MAX_MEMBER_COUNT = 10_000


class DocxPackage:
    """Manages reading, hash auditing, and lossless rebuilding of a DOCX OPC package.
    
    Implements strict raw non-target entry pass-through:
    Unchanged members copy their original local file headers, compressed payloads,
    flags, compression methods, and central-directory records without recompressing.
    """

    def __init__(self, data: bytes, max_uncompressed_bytes: int = MAX_DOCX_UNCOMPRESSED_BYTES):
        self.raw_data = data
        self.members: dict[str, bytes] = {}
        self.zip_infos: dict[str, zipfile.ZipInfo] = {}
        self.member_order: list[str] = []
        self.hashes: dict[str, str] = {}
        self.raw_compressed: dict[str, bytes] = {}
        self.raw_compressed_hashes: dict[str, str] = {}
        self._raw_local_entries: dict[str, bytes] = {}
        self._raw_cd_entries: dict[str, bytes] = {}
        self._raw_mtime: dict[str, int] = {}
        self._raw_mdate: dict[str, int] = {}

        # 1. Parse using zipfile for high-level ZipInfo & security checks
        try:
            zf = zipfile.ZipFile(io.BytesIO(data), "r")
        except zipfile.BadZipFile as e:
            raise DocxFidelityException(f"Invalid DOCX package: not a valid ZIP archive ({e})") from e

        with zf:
            infolist = zf.infolist()
            if len(infolist) > MAX_MEMBER_COUNT:
                raise DocxFidelityException(
                    f"Package security violation: member count exceeds limit ({len(infolist)} > {MAX_MEMBER_COUNT})"
                )

            total_uncompressed = 0
            for info in infolist:
                name = info.filename
                # ZipSlip protection: block directory traversal and absolute paths
                clean_norm = os.path.normpath(name).replace("\\", "/")
                if clean_norm.startswith("../") or clean_norm == ".." or os.path.isabs(name) or name.startswith("/"):
                    raise DocxFidelityException(f"ZipSlip security violation: unsafe member path '{name}'")

                # ZipBomb protection: total uncompressed budget check
                total_uncompressed += info.file_size
                if total_uncompressed > max_uncompressed_bytes:
                    raise DocxFidelityException(
                        f"ZipBomb security violation: uncompressed size exceeds limit ({total_uncompressed} > {max_uncompressed_bytes})"
                    )

                self.zip_infos[name] = info
                self.member_order.append(name)

        # 2. Binary parse of Central Directory and Local Headers from raw data
        eocd_idx = data.rfind(b"PK\x05\x06")
        if eocd_idx == -1:
            raise DocxFidelityException("Invalid DOCX package: missing EOCD record")

        (
            disk_num,
            cd_disk,
            disk_entries,
            total_entries,
            cd_size,
            cd_offset,
            comment_len,
        ) = struct.unpack("<HHHHIIH", data[eocd_idx + 4 : eocd_idx + 22])

        if total_entries != len(self.member_order):
            raise DocxFidelityException("ZIP entry count mismatch between Central Directory and ZipFile")

        cd_pos = cd_offset
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
                raise DocxFidelityException(f"Invalid Central Directory record signature at offset {cd_pos}")

            name = data[cd_pos + 46 : cd_pos + 46 + nlen].decode("utf-8", errors="replace")
            rec_len = 46 + nlen + elen + clen
            self._raw_cd_entries[name] = data[cd_pos : cd_pos + rec_len]
            self._raw_mtime[name] = mtime
            self._raw_mdate[name] = mdate
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
                raise DocxFidelityException(f"Invalid Local File Header signature for '{name}' at offset {lhoff}")

            loc_hdr_len = 30 + lnlen + lelen
            raw_comp_payload = data[lhoff + loc_hdr_len : lhoff + loc_hdr_len + csize]
            self.raw_compressed[name] = raw_comp_payload
            self.raw_compressed_hashes[name] = hashlib.sha256(raw_comp_payload).hexdigest()

            # Data descriptor handling
            desc_len = 0
            if lflags & 0x08:
                cand = data[lhoff + loc_hdr_len + csize : lhoff + loc_hdr_len + csize + 16]
                desc_len = 16 if cand.startswith(b"PK\x07\x08") else 12

            total_local_len = loc_hdr_len + csize + desc_len
            self._raw_local_entries[name] = data[lhoff : lhoff + total_local_len]

            # Decompress and verify payload
            if comp == zipfile.ZIP_STORED:
                uncomp = raw_comp_payload
            elif comp == zipfile.ZIP_DEFLATED:
                try:
                    uncomp = zlib.decompress(raw_comp_payload, -15)
                except Exception as e:
                    raise DocxFidelityException(f"Corrupted deflate stream in member '{name}': {e}") from e
            else:
                raise DocxFidelityException(f"Unsupported compression method {comp} in member '{name}'")

            if len(uncomp) != usize:
                raise DocxFidelityException(f"Uncompressed size mismatch in '{name}': expected {usize}, got {len(uncomp)}")

            calc_crc = zlib.crc32(uncomp) & 0xFFFFFFFF
            if calc_crc != crc:
                raise DocxFidelityException(f"CRC-32 checksum mismatch in '{name}': expected {crc}, got {calc_crc}")

            self.members[name] = uncomp
            self.hashes[name] = hashlib.sha256(uncomp).hexdigest()

    def get_member(self, name: str) -> bytes | None:
        """Return decompressed bytes for member."""
        return self.members.get(name)

    def get_hash(self, name: str) -> str | None:
        """Return SHA-256 of decompressed payload for member."""
        return self.hashes.get(name)

    def get_compressed_member(self, name: str) -> bytes | None:
        """Return raw compressed payload bytes for member."""
        return self.raw_compressed.get(name)

    def get_compressed_hash(self, name: str) -> str | None:
        """Return SHA-256 of raw compressed payload for member."""
        return self.raw_compressed_hashes.get(name)

    def has_member(self, name: str) -> bool:
        """Check if member exists in package."""
        return name in self.members

    def rebuild(
        self,
        changed_parts: dict[str, bytes],
        dropped_parts: set[str] | None = None,
    ) -> bytes:
        """Rebuild the ZIP package with strict raw non-target entry pass-through.
        
        Unchanged members are copied verbatim at the binary level (local header + raw compressed data),
        preserving bit-for-bit compression flags, compressed sizes, and raw compressed byte hashes.
        Changed members are encoded with compatible metadata and Deflate compression.
        """
        if not changed_parts and not dropped_parts:
            return self.raw_data

        dropped = dropped_parts or set()
        out_buf = io.BytesIO()
        new_cd_entries: list[bytes] = []
        current_offset = 0

        for name in self.member_order:
            if name in dropped:
                continue

            new_local_offset = current_offset
            name_bytes = name.encode("utf-8")

            if name not in changed_parts:
                # STRICT RAW PASS-THROUGH: Copy original local file entry verbatim
                raw_local = self._raw_local_entries[name]
                out_buf.write(raw_local)
                current_offset += len(raw_local)

                # Copy original Central Directory record, updating only local header offset (bytes 42..46)
                orig_cd = self._raw_cd_entries[name]
                new_cd = orig_cd[:42] + struct.pack("<I", new_local_offset) + orig_cd[46:]
                new_cd_entries.append(new_cd)
            else:
                # CHANGED PART: Re-encode with Deflate compression and compatible attributes
                new_uncomp = changed_parts[name]
                orig_info = self.zip_infos[name]

                if orig_info.compress_type == zipfile.ZIP_STORED:
                    comp_data = new_uncomp
                    comp_type = zipfile.ZIP_STORED
                else:
                    comp_obj = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
                    comp_data = comp_obj.compress(new_uncomp) + comp_obj.flush()
                    comp_type = zipfile.ZIP_DEFLATED

                csize = len(comp_data)
                usize = len(new_uncomp)
                crc = zlib.crc32(new_uncomp) & 0xFFFFFFFF
                mtime = self._raw_mtime.get(name, 0)
                mdate = self._raw_mdate.get(name, 0x21)

                # A11: Clear bit 3 (data descriptor) because exact CRC and sizes are written
                # directly into the local header without trailing descriptor.
                new_flag_bits = orig_info.flag_bits & ~0x08

                # Local File Header
                loc_hdr = struct.pack(
                    "<IHHHHHIIIHH",
                    0x04034B50,
                    orig_info.extract_version,
                    new_flag_bits,
                    comp_type,
                    mtime,
                    mdate,
                    crc,
                    csize,
                    usize,
                    len(name_bytes),
                    0,  # extra field length
                ) + name_bytes
                out_buf.write(loc_hdr)
                out_buf.write(comp_data)
                current_offset += len(loc_hdr) + csize

                # Central Directory Header
                cd_hdr = struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,
                    orig_info.create_version,
                    orig_info.extract_version,
                    new_flag_bits,
                    comp_type,
                    mtime,
                    mdate,
                    crc,
                    csize,
                    usize,
                    len(name_bytes),
                    0,  # extra length
                    0,  # comment length
                    0,  # disk number start
                    orig_info.internal_attr,
                    orig_info.external_attr,
                    new_local_offset,
                ) + name_bytes
                new_cd_entries.append(cd_hdr)

        # Write Central Directory
        cd_start_offset = current_offset
        for cd_entry in new_cd_entries:
            out_buf.write(cd_entry)
        cd_size = out_buf.tell() - cd_start_offset
        total_records = len(new_cd_entries)

        # Write End of Central Directory (EOCD)
        eocd = struct.pack(
            "<IHHHHIIH",
            0x06054B50,
            0,              # disk number
            0,              # disk where CD starts
            total_records,  # records on this disk
            total_records,  # total records
            cd_size,        # CD size in bytes
            cd_start_offset,# CD offset
            0,              # comment length
        )
        out_buf.write(eocd)

        return out_buf.getvalue()
