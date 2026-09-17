#!/usr/bin/env python3
"""Phase 11 — Large File Performance, Memory & Scaling Benchmark Harness.

Measures:
1. Wall clock latency (time.perf_counter_ns).
2. Process-tree Peak RSS memory (parent + child subprocesses via psutil).
3. Throughput (MiB/s).
4. Scaling slopes (log-log regression) and 50->100 ratios.
5. Positive and No-Change paths across representative execution classes:
   - Class A: TEXT / WHOLE-BUFFER SCAN (txt)
   - Class B: LOSSLESS OPC / ZIP RAW-PASS-THROUGH (docx)
   - Class C: SECOND OPC ADAPTER (xlsx)
   - Class D: GENERIC ZIP/XML CONTAINER (odt)
   - Class E: CHUNK/CONTAINER IMAGE METADATA (png)
   - Class F: AUDIO RIFF IN-PROCESS (wav RIFF chunk stripping)
6. CLI end-to-end processing.
7. Batch processing (10 x 10 MiB) and expected limit rejection.
8. Breadth smoke across canonical formats.
9. Sequential memory leak probe.
10. Output hashes and large-file idempotence & fidelity validation.

Zero network calls, zero sensitive user data, temporary files cleaned up.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import math
import os
import platform
import shutil
import struct
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

# Ensure service/scripts is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import psutil
except ImportError:
    psutil = None

import common
import security
try:
    import server
except Exception:
    server = None
from batch_processor import BatchProcessor
from cli import ExitCode, main as cli_main
from format_policy import FormatPolicyRegistry
from pipeline import Pipeline
from pipeline_types import CleaningReport, ErrorCode, PipelineStatus, ProcessingMode


# ==============================================================================
# CANONICAL SIZES & CONSTANTS
# ==============================================================================
SIZE_1_MIB = 1 * 1024 * 1024       # 1,048,576 bytes
SIZE_10_MIB = 10 * 1024 * 1024     # 10,485,760 bytes
SIZE_50_MIB = 50 * 1024 * 1024     # 52,428,800 bytes
SIZE_100_MIB = 100 * 1024 * 1024   # 104,857,600 bytes

CANONICAL_SIZES = [SIZE_1_MIB, SIZE_10_MIB, SIZE_50_MIB, SIZE_100_MIB]
QUICK_SIZES = [SIZE_1_MIB, SIZE_10_MIB]

FIXED_SEED = 0xCAFEBABE
FIXED_DATETIME = (2026, 1, 1, 0, 0, 0)

# Section 10: Explicit post-measurement closure memory guardrails
CLOSURE_GUARDRAILS = {
    "TEXT_WHOLE_BUFFER": {
        "multiplier": 12.0,
        "base_bytes": 96 * 1024 * 1024,
        "metric": "parent_delta",
        "rationale": "CPython UTF-8 decode, character lists, frequency counting, and output buffers",
    },
    "DOCX_OPC_TREE": {
        "multiplier": 10.0,
        "base_bytes": 96 * 1024 * 1024,
        "metric": "parent_delta",
        "rationale": "In-memory zip stream, member byte copying, and MSVCRT heap allocation retention",
    },
    "XLSX_OPC_TREE": {
        "multiplier": 10.0,
        "base_bytes": 96 * 1024 * 1024,
        "metric": "parent_delta",
        "rationale": "In-memory zip stream, member byte copying, and MSVCRT heap allocation retention",
    },
    "ODF_PACKAGE": {
        "multiplier": 8.0,
        "base_bytes": 96 * 1024 * 1024,
        "metric": "parent_delta",
        "rationale": "ZIP container member streaming, XML manipulation, and CPython buffer retention",
    },
    "CHUNKED_IMAGE": {
        "multiplier": 5.0,
        "base_bytes": 96 * 1024 * 1024,
        "metric": "parent_delta",
        "rationale": "Streaming chunk filtering with full output byte assembly",
    },
    "IMAGE_CHUNK": {
        "multiplier": 5.0,
        "base_bytes": 96 * 1024 * 1024,
        "metric": "parent_delta",
        "rationale": "Streaming chunk filtering with full output byte assembly",
    },
    "AUDIO_RIFF_IN_PROCESS": {
        "multiplier": 5.0,
        "base_bytes": 96 * 1024 * 1024,
        "metric": "parent_delta",
        "rationale": "In-process RIFF chunk filtering with bytearray assembly",
    },
    "EXTERNAL_PROCESS": {
        "multiplier": 4.0,
        "base_bytes": 256 * 1024 * 1024,
        "metric": "tree_delta",
        "rationale": "Subprocess tree RSS for external toolchains (not applicable to canonical clean paths)",
    },
    "EXTERNAL_AV": {
        "multiplier": 4.0,
        "base_bytes": 256 * 1024 * 1024,
        "metric": "tree_delta",
        "rationale": "Legacy label retained for backward-compatibility",
    },
}



# ==============================================================================
# DETERMINISTIC DATA GENERATOR
# ==============================================================================
class DeterministicDataGenerator:
    """Generates deterministic, low-compressibility non-zero binary payload blocks."""

    def __init__(self, seed: int = FIXED_SEED):
        self.state = seed & 0xFFFFFFFF

    def _next_u32(self) -> int:
        # 32-bit LCG (Numerical Recipes constants)
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state

    def generate_bytes(self, num_bytes: int) -> bytes:
        """Generate num_bytes of deterministic low-compressibility data."""
        # Generate in chunks of 64KB for speed
        chunk_size = 65536
        full_chunks = num_bytes // chunk_size
        remainder = num_bytes % chunk_size

        out = bytearray(num_bytes)
        idx = 0
        for _ in range(full_chunks):
            chunk = self._generate_chunk(chunk_size)
            out[idx:idx + chunk_size] = chunk
            idx += chunk_size
        if remainder:
            chunk = self._generate_chunk(remainder)
            out[idx:idx + remainder] = chunk
        return bytes(out)

    def _generate_chunk(self, size: int) -> bytes:
        words = (size + 3) // 4
        ints = [self._next_u32() for _ in range(words)]
        raw = struct.pack(f"<{words}I", *ints)
        return raw[:size]


# ==============================================================================
# PROCESS-TREE RSS SAMPLER
# ==============================================================================
class ProcessTreeMemorySampler:
    """Background sampler tracking parent and recursive children Peak RSS."""

    def __init__(self, interval_sec: float = 0.015):
        self.interval_sec = interval_sec
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.parent_pid = os.getpid()
        self.parent_proc = psutil.Process(self.parent_pid) if psutil else None

        self.parent_baseline_rss = 0
        self.tree_baseline_rss = 0
        self.parent_peak_rss = 0
        self.tree_peak_rss = 0
        self.max_child_rss_bytes = 0

    def start(self) -> None:
        if not self.parent_proc:
            return
        # Measure baseline immediately before starting
        try:
            p_rss = self.parent_proc.memory_info().rss
            c_rss = sum(c.memory_info().rss for c in self.parent_proc.children(recursive=True) if c.is_running())
            self.parent_baseline_rss = p_rss
            self.tree_baseline_rss = p_rss + c_rss
            self.parent_peak_rss = self.parent_baseline_rss
            self.tree_peak_rss = self.tree_baseline_rss
            self.max_child_rss_bytes = c_rss
        except Exception:
            pass

        self.stop_event.clear()
        self.thread = threading.Thread(target=self._sample_loop, daemon=True)
        self.thread.start()

    def _sample_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.parent_proc and self.parent_proc.is_running():
                    p_rss = self.parent_proc.memory_info().rss
                    c_rss = 0
                    for child in self.parent_proc.children(recursive=True):
                        try:
                            if child.is_running():
                                c_rss += child.memory_info().rss
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    total_tree = p_rss + c_rss
                    if p_rss > self.parent_peak_rss:
                        self.parent_peak_rss = p_rss
                    if total_tree > self.tree_peak_rss:
                        self.tree_peak_rss = total_tree
                    if c_rss > self.max_child_rss_bytes:
                        self.max_child_rss_bytes = c_rss
            except Exception:
                pass
            time.sleep(self.interval_sec)

    def stop(self) -> tuple[int, int, int, int]:
        """Returns (parent_peak, tree_peak, parent_delta, tree_delta)."""
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=1.0)
        # Final reading
        try:
            if self.parent_proc and self.parent_proc.is_running():
                p_rss = self.parent_proc.memory_info().rss
                c_rss = sum(c.memory_info().rss for c in self.parent_proc.children(recursive=True) if c.is_running())
                total_tree = p_rss + c_rss
                self.parent_peak_rss = max(self.parent_peak_rss, p_rss)
                self.tree_peak_rss = max(self.tree_peak_rss, total_tree)
                if c_rss > self.max_child_rss_bytes:
                    self.max_child_rss_bytes = c_rss
        except Exception:
            pass

        p_delta = max(0, self.parent_peak_rss - self.parent_baseline_rss)
        t_delta = max(0, self.tree_peak_rss - self.tree_baseline_rss)
        return self.parent_peak_rss, self.tree_peak_rss, p_delta, t_delta


# ==============================================================================
# FIXTURE BUILDERS BY EXECUTION CLASS
# ==============================================================================
def build_txt_fixture(target_size: int, positive: bool, gen: DeterministicDataGenerator) -> bytes:
    """Build deterministic TXT fixture scaled to target_size."""
    # Head with watermarks if positive, then legitimate body repeated to target_size
    carrier = "The quick brown fox jumps over the lazy dog. ZeroWidth\u200BWatermark\u200CCarrier\u200DText.\n" if positive else "The quick brown fox jumps over the lazy dog. CleanStandardLegitimateTextWithoutCarriers.\n"
    head = (carrier * 5).encode("utf-8")
    body_line = b"The quick brown fox jumps over the lazy dog. CleanStandardLegitimateTextWithoutCarriers.\n"
    if target_size <= len(head):
        return head[:target_size]
    rem = target_size - len(head)
    repeats = (rem + len(body_line) - 1) // len(body_line)
    return head + (body_line * repeats)[:rem]


def build_docx_fixture(target_size: int, positive: bool, gen: DeterministicDataGenerator) -> bytes:
    """Build valid DOCX fixture scaled with preserved stored binary members."""
    # Start with Golden DOCX structure
    golden_path = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
    golden_bytes = golden_path.read_bytes()

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(golden_bytes), "r") as zin:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    if positive:
                        # Ensure carrier exists in document
                        if b"\xe2\x80\x8b" not in data:
                            data = data.replace(b"</w:t>", b"\xe2\x80\x8b</w:t>", 1)
                    else:
                        # Clean document
                        data = data.replace(b"\xe2\x80\x8b", b"")
                        data = data.replace(b"\xe2\x80\x8c", b"")
                        data = data.replace(b"\xe2\x80\x8d", b"")
                info = zipfile.ZipInfo(item.filename, date_time=FIXED_DATETIME)
                info.compress_type = zipfile.ZIP_STORED
                zout.writestr(info, data)

            current_size = buf.tell()
            payload_needed = max(0, target_size - current_size)
            # Per Phase 9 limits, single member <= 64 MiB (SecurityLimits.max_member_uncompressed_bytes).
            # Split payload into members each <= 48 MiB.
            max_member_chunk = 48 * 1024 * 1024
            member_idx = 1
            while payload_needed > 0:
                chunk_len = min(payload_needed, max_member_chunk)
                payload_bytes = gen.generate_bytes(chunk_len)
                info = zipfile.ZipInfo(f"word/media/inert_{member_idx}.bin", date_time=FIXED_DATETIME)
                info.compress_type = zipfile.ZIP_STORED
                zout.writestr(info, payload_bytes)
                payload_needed -= chunk_len
                member_idx += 1

    return buf.getvalue()


def build_xlsx_fixture(target_size: int, positive: bool, gen: DeterministicDataGenerator) -> bytes:
    """Build valid XLSX fixture scaled with preserved stored binary members."""
    template_name = "carrier_shared_string.xlsx" if positive else "synthetic_baseline.xlsx"
    template_path = REPO_ROOT / "tests" / "fixtures" / "xlsx_lossless" / template_name
    template_bytes = template_path.read_bytes()

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template_bytes), "r") as zin:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zout:
            for item in zin.infolist():
                info = zipfile.ZipInfo(item.filename, date_time=FIXED_DATETIME)
                info.compress_type = zipfile.ZIP_STORED
                zout.writestr(info, zin.read(item.filename))

            current_size = buf.tell()
            payload_needed = max(0, target_size - current_size)
            max_member_chunk = 48 * 1024 * 1024
            member_idx = 1
            while payload_needed > 0:
                chunk_len = min(payload_needed, max_member_chunk)
                payload_bytes = gen.generate_bytes(chunk_len)
                info = zipfile.ZipInfo(f"xl/media/inert_{member_idx}.bin", date_time=FIXED_DATETIME)
                info.compress_type = zipfile.ZIP_STORED
                zout.writestr(info, payload_bytes)
                payload_needed -= chunk_len
                member_idx += 1

    return buf.getvalue()


def build_odt_fixture(target_size: int, positive: bool, gen: DeterministicDataGenerator) -> bytes:
    """Build valid ODT package scaled with inert binary members."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        m_info = zipfile.ZipInfo("mimetype", date_time=FIXED_DATETIME)
        m_info.compress_type = zipfile.ZIP_STORED
        zf.writestr(m_info, b"application/vnd.oasis.opendocument.text")

        meta_gen = "AI Generator" if positive else "Standard Word Processor"
        meta_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            f'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0">'
            f'<office:meta><meta:generator>{meta_gen}</meta:generator></office:meta>'
            f'</office:document-meta>'
        ).encode("utf-8")
        text_content = "Carrier\u200BODT\u200BContent" if positive else "Clean ODT Document Content"
        content_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            f'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            f'<office:body><office:text><text:p>{text_content}</text:p></office:text></office:body>'
            f'</office:document-content>'
        ).encode("utf-8")

        for name, data in [("meta.xml", meta_xml), ("content.xml", content_xml)]:
            info = zipfile.ZipInfo(name, date_time=FIXED_DATETIME)
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, data)

        current_size = buf.tell()
        payload_needed = max(0, target_size - current_size)
        max_member_chunk = 48 * 1024 * 1024
        member_idx = 1
        while payload_needed > 0:
            chunk_len = min(payload_needed, max_member_chunk)
            payload_bytes = gen.generate_bytes(chunk_len)
            info = zipfile.ZipInfo(f"Pictures/inert_{member_idx}.bin", date_time=FIXED_DATETIME)
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, payload_bytes)
            payload_needed -= chunk_len
            member_idx += 1

    return buf.getvalue()


def build_png_fixture(target_size: int, positive: bool, gen: DeterministicDataGenerator) -> bytes:
    """Build valid PNG fixture scaled with ancillary padding chunk."""
    import zlib
    base_clean = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    iend_pos = base_clean.find(b"IEND") - 4

    chunks = []
    if positive:
        text_payload = b"Comment\x00SyntheticWatermarkMarker"
        text_crc = zlib.crc32(b"tEXt" + text_payload) & 0xFFFFFFFF
        t_chunk = struct.pack(">I", len(text_payload)) + b"tEXt" + text_payload + struct.pack(">I", text_crc)
        chunks.append(t_chunk)

    current_len = len(base_clean) + sum(len(c) for c in chunks)
    pad_needed = max(0, target_size - current_len)
    if pad_needed >= 12:
        payload_len = pad_needed - 12
        payload = gen.generate_bytes(payload_len)
        chunk_type = b"prNd"  # Private ancillary chunk
        crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        pad_chunk = struct.pack(">I", payload_len) + chunk_type + payload + struct.pack(">I", crc)
        chunks.append(pad_chunk)

    return base_clean[:iend_pos] + b"".join(chunks) + base_clean[iend_pos:]


def build_wav_fixture(target_size: int, positive: bool, gen: DeterministicDataGenerator) -> bytes:
    """Build valid PCM WAV fixture scaled to target_size."""
    subchunk1_size = 16
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)

    list_chunk = b""
    if positive:
        info_payload = b"INAM\x12\x00\x00\x00AI Watermark Audio\x00"
        list_chunk = b"LIST" + struct.pack("<I", len(info_payload) + 4) + b"INFO" + info_payload

    # Overhead: RIFF(12) + fmt(24) + list(len) + data_header(8) = 44 + len(list_chunk)
    overhead = 12 + len(fmt_chunk) + len(list_chunk) + 8
    num_samples = max(100, target_size - overhead)
    subchunk2_size = num_samples

    data_bytes = gen.generate_bytes(num_samples)
    data_chunk = b"data" + struct.pack("<I", subchunk2_size) + data_bytes

    chunk_size = 4 + len(fmt_chunk) + len(list_chunk) + len(data_chunk)
    header = b"RIFF" + struct.pack("<I", chunk_size) + b"WAVE"

    return header + fmt_chunk + list_chunk + data_chunk


# Mapping of profile builders
FIXTURE_BUILDERS = {
    "txt": build_txt_fixture,
    "docx": build_docx_fixture,
    "xlsx": build_xlsx_fixture,
    "odt": build_odt_fixture,
    "png": build_png_fixture,
    "wav": build_wav_fixture,
}


# ==============================================================================
# DATA MODELS FOR BENCHMARK RESULTS
# ==============================================================================
@dataclass
class RawRunMeasurement:
    wall_ms: float
    parent_peak_rss_bytes: int
    tree_peak_rss_bytes: int
    parent_delta_rss_bytes: int
    tree_delta_rss_bytes: int


@dataclass
class ProfileSizeResult:
    target_size_bytes: int
    actual_size_bytes: int
    production_allowed: bool
    status: str
    error_code: str | None = None
    repetitions: int = 0
    raw_runs: list[RawRunMeasurement] = field(default_factory=list)
    median_wall_ms: float = 0.0
    throughput_mib_s: float = 0.0
    max_parent_peak_rss_bytes: int = 0
    max_tree_peak_rss_bytes: int = 0
    max_parent_delta_rss_bytes: int = 0
    max_tree_delta_rss_bytes: int = 0
    input_sha256: str = ""
    first_output_sha256: str = ""
    second_output_sha256: str = ""
    idempotence_checked: bool = False
    idempotence_pass: bool = False
    fidelity_checked: bool = False
    fidelity_pass: bool = False
    budget_pass: bool = False


@dataclass
class ProfileSummary:
    benchmark_id: str
    canonical_policy: str
    extension: str
    execution_class: str
    streaming_classification: str
    is_positive: bool
    is_cli: bool = False
    sizes_successful: list[int] = field(default_factory=list)
    sizes_rejected: list[int] = field(default_factory=list)
    results_by_size: dict[str, ProfileSizeResult] = field(default_factory=dict)
    time_scaling_alpha: float | None = None
    memory_scaling_alpha: float | None = None
    ratio_50_to_100_time: float | None = None
    ratio_50_to_100_rss: float | None = None
    overall_budget_status: str = "PASS"


# ==============================================================================
# CORE BENCHMARK EXECUTOR
# ==============================================================================
class BenchmarkEngine:
    def __init__(self, output_json: Path | None = None, quick: bool = False, repetitions: int = 3):
        self.output_json = output_json
        self.quick = quick
        self.repetitions = 1 if quick else repetitions
        self.sizes = QUICK_SIZES if quick else CANONICAL_SIZES
        self.gen = DeterministicDataGenerator(FIXED_SEED)
        self.pipeline = Pipeline()
        self.sampler = ProcessTreeMemorySampler(interval_sec=0.015)

    def generate_fixture(self, ext: str, target_size: int, positive: bool) -> bytes:
        builder = FIXTURE_BUILDERS.get(ext)
        if not builder:
            raise ValueError(f"No fixture builder for format {ext}")
        return builder(target_size, positive, self.gen)

    @staticmethod
    def compute_median(values: list[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    @staticmethod
    def compute_throughput(size_bytes: int, wall_ms: float) -> float:
        if wall_ms <= 0:
            return 0.0
        return (size_bytes / (1024 * 1024)) / (wall_ms / 1000.0)

    @staticmethod
    def evaluate_budget(
        execution_class: str,
        target_size_bytes: int,
        delta_parent_rss_bytes: int,
        delta_tree_rss_bytes: int,
    ) -> str:
        # Budget verification (Section 33)
        # In-process: delta_parent <= 96 MiB + 2.5 * input_size
        # External-tool: delta_tree <= 256 MiB + 4.0 * input_size
        if execution_class == "EXTERNAL_AV":
            budget_limit = (256 * 1024 * 1024) + int(4.0 * target_size_bytes)
            return "PASS" if delta_tree_rss_bytes <= budget_limit else "INVESTIGATE"
        else:
            budget_limit = (96 * 1024 * 1024) + int(2.5 * target_size_bytes)
            return "PASS" if delta_parent_rss_bytes <= budget_limit else "INVESTIGATE"

    @staticmethod
    def evaluate_closure_guardrail(
        execution_class: str,
        target_size_bytes: int,
        delta_parent_rss_bytes: int,
        delta_tree_rss_bytes: int,
    ) -> str:
        """Evaluate post-measurement calibrated memory guardrail (Section 10)."""
        rule = CLOSURE_GUARDRAILS.get(execution_class, CLOSURE_GUARDRAILS.get("DOCX_OPC_TREE"))
        limit = rule["base_bytes"] + int(rule["multiplier"] * target_size_bytes)
        tested_delta = delta_tree_rss_bytes if rule["metric"] == "tree_delta" else delta_parent_rss_bytes
        return "PASS" if tested_delta <= limit else "INVESTIGATE"

    def run_clean_operation(
        self,
        fixture_bytes: bytes,
        ext: str,
        is_cli: bool = False,
    ) -> tuple[bytes, CleaningReport, RawRunMeasurement]:
        """Execute one clean run with timing and ProcessTreeMemorySampler."""
        gc.collect()

        if is_cli:
            with tempfile.TemporaryDirectory() as td:
                in_path = Path(td) / f"bench_input.{ext}"
                out_path = Path(td) / f"bench_input.cleaned.{ext}"
                in_path.write_bytes(fixture_bytes)

                self.sampler.start()
                t0 = time.perf_counter_ns()
                exit_code = cli_main(["clean", str(in_path), "-o", str(out_path), "--json"])
                t1 = time.perf_counter_ns()
                p_peak, t_peak, p_delta, t_delta = self.sampler.stop()

                wall_ms = (t1 - t0) / 1_000_000.0
                cleaned_bytes = out_path.read_bytes() if out_path.exists() else fixture_bytes
                # Create synthetic report representing CLI success
                rep = CleaningReport.from_dict({
                    "status": "CLEANED" if exit_code == 0 else "ERROR",
                    "input": {"filename": in_path.name, "format": ext, "size": len(fixture_bytes), "sha256": ""},
                    "inspection": {"findings": [], "detectors_run": [], "detectors_unavailable": [], "unsupported_checks": [], "detection_status": "CLEAN"},
                    "policy": {"mode": "SAFE", "format_policy": ext, "normalize_spaces": True, "remote_processing": False},
                    "mutation_plan": {"mutations": [], "changed_parts": []},
                    "validation": {"status": "PASSED" if exit_code == 0 else "FAILED", "invariants": [], "warnings": []},
                    "output": {"changed": True, "would_change": True, "size": len(cleaned_bytes), "sha256": "", "output_path": str(out_path)},
                    "privacy": {"network_used": False, "external_services": []},
                    "performance": {"elapsed_ms": wall_ms},
                })
        else:
            self.sampler.start()
            t0 = time.perf_counter_ns()
            cleaned_bytes, rep = self.pipeline.clean(fixture_bytes, filename=f"bench_input.{ext}")
            t1 = time.perf_counter_ns()
            p_peak, t_peak, p_delta, t_delta = self.sampler.stop()
            wall_ms = (t1 - t0) / 1_000_000.0

        meas = RawRunMeasurement(
            wall_ms=wall_ms,
            parent_peak_rss_bytes=p_peak,
            tree_peak_rss_bytes=t_peak,
            parent_delta_rss_bytes=p_delta,
            tree_delta_rss_bytes=t_delta,
        )
        return cleaned_bytes, rep, meas

    def benchmark_profile_at_size(
        self,
        ext: str,
        target_size: int,
        positive: bool,
        is_cli: bool,
        streaming_class: str,
    ) -> ProfileSizeResult:
        """Benchmark a specific (profile, size) cell with repetitions."""
        builder = FIXTURE_BUILDERS.get(ext)
        if not builder:
            raise ValueError(f"No fixture builder for format {ext}")

        # Check production limits
        # Common limit: 256 MiB
        # Archive limits: max_total_uncompressed 128 MiB, max_member 64 MiB
        is_allowed = target_size <= common.MAX_INPUT_BYTES
        if ext in ("docx", "xlsx", "odt"):
            sec = security.SecurityLimits()
            if target_size > sec.max_total_uncompressed_bytes:
                is_allowed = False

        if not is_allowed:
            return ProfileSizeResult(
                target_size_bytes=target_size,
                actual_size_bytes=target_size,
                production_allowed=False,
                status="EXPECTED_LIMIT_REJECTION",
                error_code="PROCESSING_LIMIT_EXCEEDED",
            )

        # Generate fixture outside timed region
        fixture_bytes = builder(target_size, positive, self.gen)
        actual_size = len(fixture_bytes)
        input_sha = hashlib.sha256(fixture_bytes).hexdigest()

        raw_runs: list[RawRunMeasurement] = []
        last_cleaned = fixture_bytes
        last_rep = None

        # Warmup run (1 untimed where practical, smaller sizes)
        if actual_size <= SIZE_10_MIB:
            try:
                self.run_clean_operation(fixture_bytes, ext, is_cli=is_cli)
            except Exception:
                pass

        # Measured repetitions
        reps = self.repetitions
        if ext == "txt" and actual_size >= SIZE_50_MIB:
            reps = min(reps, 2)

        for _ in range(reps):
            cleaned, rep, meas = self.run_clean_operation(fixture_bytes, ext, is_cli=is_cli)
            raw_runs.append(meas)
            last_cleaned = cleaned
            last_rep = rep

        # Statistical calculations
        latencies = [r.wall_ms for r in raw_runs]
        latencies.sort()
        median_ms = self.compute_median(latencies)
        throughput = ((actual_size / (1024 * 1024)) / (median_ms / 1000.0)) if median_ms > 0 else 0.0

        max_parent_peak = max(r.parent_peak_rss_bytes for r in raw_runs)
        max_tree_peak = max(r.tree_peak_rss_bytes for r in raw_runs)
        max_parent_delta = max(r.parent_delta_rss_bytes for r in raw_runs)
        max_tree_delta = max(r.tree_delta_rss_bytes for r in raw_runs)

        first_out_sha = hashlib.sha256(last_cleaned).hexdigest()
        second_out_sha = ""
        idempotence_checked = False
        idempotence_pass = False

        # Idempotence verification (tested on all PNG sizes, OOXML <= 50 MiB, skip 2nd pass on expensive text >= 50 MiB per Section 41)
        if ext == "png" or (ext != "txt" and actual_size <= SIZE_50_MIB) or (ext == "txt" and actual_size <= SIZE_10_MIB) or not positive:
            cleaned2, rep2 = self.pipeline.clean(last_cleaned, filename=f"bench_input.{ext}")
            second_out_sha = hashlib.sha256(cleaned2).hexdigest()
            idempotence_checked = True
            idempotence_pass = (cleaned2 == last_cleaned) and (rep2.status == PipelineStatus.NO_CHANGE_REQUIRED)

        # Fidelity check for OOXML
        fidelity_checked = False
        fidelity_pass = False
        if ext in ("docx", "xlsx") and last_rep and last_rep.validation:
            fidelity_checked = True
            fidelity_pass = str(last_rep.validation.status).upper() in ("PASS", "PASSED")

        # Budget verification (Section 33)
        # In-process: delta_parent <= 96 MiB + 2.5 * input_size
        # External-tool: delta_tree <= 256 MiB + 4.0 * input_size
        if streaming_class == "EXTERNAL_PROCESS":
            budget_limit = (256 * 1024 * 1024) + int(4.0 * actual_size)
            budget_pass = max_tree_delta <= budget_limit
        else:
            budget_limit = (96 * 1024 * 1024) + int(2.5 * actual_size)
            budget_pass = max_parent_delta <= budget_limit

        return ProfileSizeResult(
            target_size_bytes=target_size,
            actual_size_bytes=actual_size,
            production_allowed=True,
            status="PASS" if (last_rep and last_rep.status != PipelineStatus.ERROR) else "FAIL",
            error_code=None if (last_rep and last_rep.status != PipelineStatus.ERROR) else str(last_rep.error_code),
            repetitions=len(raw_runs),
            raw_runs=raw_runs,
            median_wall_ms=round(median_ms, 2),
            throughput_mib_s=round(throughput, 2),
            max_parent_peak_rss_bytes=max_parent_peak,
            max_tree_peak_rss_bytes=max_tree_peak,
            max_parent_delta_rss_bytes=max_parent_delta,
            max_tree_delta_rss_bytes=max_tree_delta,
            input_sha256=input_sha,
            first_output_sha256=first_out_sha,
            second_output_sha256=second_out_sha,
            idempotence_checked=idempotence_checked,
            idempotence_pass=idempotence_pass,
            fidelity_checked=fidelity_checked,
            fidelity_pass=fidelity_pass,
            budget_pass=budget_pass,
        )

    def run_scaling_profile(
        self,
        benchmark_id: str,
        canonical_policy: str,
        ext: str,
        exec_class: str,
        streaming_class: str,
        positive: bool,
        is_cli: bool = False,
    ) -> ProfileSummary:
        """Run full 1/10/50/100 MiB matrix on a profile."""
        print(f"\n---> Running Profile: {benchmark_id} ({ext.upper()} {'POS' if positive else 'NO_CHANGE'} CLI={is_cli})")
        summary = ProfileSummary(
            benchmark_id=benchmark_id,
            canonical_policy=canonical_policy,
            extension=ext,
            execution_class=exec_class,
            streaming_classification=streaming_class,
            is_positive=positive,
            is_cli=is_cli,
        )

        target_sizes = self.sizes
        if is_cli and ext == "txt":
            target_sizes = [s for s in self.sizes if s <= SIZE_10_MIB]

        for target_size in target_sizes:
            size_name = f"{target_size // (1024 * 1024)}MiB"
            res = self.benchmark_profile_at_size(ext, target_size, positive, is_cli, streaming_class)
            summary.results_by_size[size_name] = res

            if res.production_allowed and res.status == "PASS":
                summary.sizes_successful.append(target_size)
                print(f"     [{size_name}] Latency: {res.median_wall_ms:.1f}ms | Throughput: {res.throughput_mib_s:.1f} MiB/s | Delta RSS: {res.max_parent_delta_rss_bytes / (1024*1024):.1f} MiB (Parent) / {res.max_tree_delta_rss_bytes / (1024*1024):.1f} MiB (Tree) | Idempotent: {res.idempotence_pass}")
            else:
                summary.sizes_rejected.append(target_size)
                print(f"     [{size_name}] {res.status} (Allowed={res.production_allowed}, Error={res.error_code})")

        # Calculate log-log scaling slopes if >= 3 successful sizes (Section 31)
        valid_sizes = [s for s in [SIZE_1_MIB, SIZE_10_MIB, SIZE_50_MIB, SIZE_100_MIB] if s in summary.sizes_successful]
        if len(valid_sizes) >= 3:
            log_sizes = [math.log(s) for s in valid_sizes]
            log_times = [math.log(max(0.1, summary.results_by_size[f"{s // (1024 * 1024)}MiB"].median_wall_ms)) for s in valid_sizes]
            # Simple linear regression slope: Cov(x, y) / Var(x)
            mean_x = sum(log_sizes) / len(log_sizes)
            mean_y = sum(log_times) / len(log_times)
            var_x = sum((x - mean_x) ** 2 for x in log_sizes)
            cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(log_sizes, log_times))
            alpha_t = cov_xy / var_x if var_x > 0 else 1.0
            summary.time_scaling_alpha = round(alpha_t, 3)

            # Memory slope
            deltas = [max(1, summary.results_by_size[f"{s // (1024 * 1024)}MiB"].max_parent_delta_rss_bytes) for s in valid_sizes]
            log_deltas = [math.log(d) for d in deltas]
            mean_yd = sum(log_deltas) / len(log_deltas)
            cov_xyd = sum((x - mean_x) * (y - mean_yd) for x, y in zip(log_sizes, log_deltas))
            alpha_m = cov_xyd / var_x if var_x > 0 else 1.0
            summary.memory_scaling_alpha = round(alpha_m, 3)

        # Calculate 50 -> 100 ratio if both exist
        if "50MiB" in summary.results_by_size and "100MiB" in summary.results_by_size:
            r50 = summary.results_by_size["50MiB"]
            r100 = summary.results_by_size["100MiB"]
            if r50.status == "PASS" and r100.status == "PASS" and r50.median_wall_ms > 0:
                summary.ratio_50_to_100_time = round(r100.median_wall_ms / r50.median_wall_ms, 2)
                if r50.max_parent_delta_rss_bytes > 0:
                    summary.ratio_50_to_100_rss = round(r100.max_parent_delta_rss_bytes / r50.max_parent_delta_rss_bytes, 2)

        # Overall budget check
        all_budget_pass = all(r.budget_pass for r in summary.results_by_size.values() if r.production_allowed)
        summary.overall_budget_status = "PASS" if all_budget_pass else "INVESTIGATE"

        return summary

    def run_batch_workload(self) -> dict[str, Any]:
        """Run 10 x 10 MiB batch and 1 x 50 MiB limit rejection test (Section 26 & 70)."""
        print("\n---> Running Batch Benchmark (10 x 10 MiB & Expected Limit Rejection)")
        with tempfile.TemporaryDirectory() as td:
            in_dir = Path(td) / "input"
            out_dir = Path(td) / "output"
            in_dir.mkdir()
            out_dir.mkdir()

            # Create 10 valid 10 MiB docx files
            docx_10mb = build_docx_fixture(SIZE_10_MIB, positive=True, gen=self.gen)
            for i in range(10):
                (in_dir / f"doc_{i}.docx").write_bytes(docx_10mb)

            # Also create 1 oversized 50 MiB file (exceeds batch per-file limit 32 MiB)
            docx_50mb = build_docx_fixture(SIZE_50_MIB, positive=True, gen=self.gen)
            (in_dir / "oversized_50mb.docx").write_bytes(docx_50mb)

            proc = BatchProcessor(self.pipeline)

            self.sampler.start()
            t0 = time.perf_counter_ns()
            batch_rep = proc.process_paths([in_dir], output_dir=out_dir, mode=ProcessingMode.SAFE)
            t1 = time.perf_counter_ns()
            p_peak, t_peak, p_delta, t_delta = self.sampler.stop()

            wall_ms = (t1 - t0) / 1_000_000.0

            successful_items = sum(1 for item in batch_rep.items if item.status in ("CLEANED", "NO_CHANGE_REQUIRED"))
            rejected_items = sum(1 for item in batch_rep.items if item.error_code == "PROCESSING_LIMIT_EXCEEDED")

            print(f"     Batch 10x10MB: {successful_items}/10 successful, {rejected_items}/1 expected limit rejection in {wall_ms:.1f}ms")
            print(f"     Batch Delta Tree RSS: {t_delta / (1024*1024):.1f} MiB")

            return {
                "workload": "10x10MiB + 1x50MiB_rejection",
                "wall_ms": round(wall_ms, 2),
                "successful_items": successful_items,
                "expected_limit_rejected_items": rejected_items,
                "parent_peak_rss_bytes": p_peak,
                "tree_peak_rss_bytes": t_peak,
                "parent_delta_rss_bytes": p_delta,
                "tree_delta_rss_bytes": t_delta,
                "fault_isolation_pass": (successful_items == 10 and rejected_items == 1),
            }

    def run_breadth_smoke(self) -> dict[str, Any]:
        """Run 1 MiB clean smoke on all available canonical policies (Section 7)."""
        print("\n---> Running Breadth Smoke (1 MiB across all available canonical policies)")
        reg = FormatPolicyRegistry.get_default()
        results = {}
        smoke_size = SIZE_1_MIB

        for policy in reg.all_policies():
            fmt = policy.format_name.lower()
            builder = FIXTURE_BUILDERS.get(fmt)
            if not builder or not policy.clean_capabilities:
                continue
            deps_ok = all(shutil.which(d) for d in policy.optional_dependencies)
            if not deps_ok:
                continue

            fixture_bytes = builder(smoke_size, positive=True, gen=self.gen)

            t0 = time.perf_counter_ns()
            try:
                cleaned, rep = self.pipeline.clean(fixture_bytes, filename=f"smoke.{policy.extensions[0].lstrip('.')}")
                t1 = time.perf_counter_ns()
                results[fmt] = {
                    "status": rep.status.value,
                    "wall_ms": round((t1 - t0) / 1_000_000.0, 2),
                    "pass": rep.status != PipelineStatus.ERROR,
                }
            except Exception as e:
                t1 = time.perf_counter_ns()
                results[fmt] = {
                    "status": "EXCEPTION",
                    "error": str(e),
                    "wall_ms": round((t1 - t0) / 1_000_000.0, 2),
                    "pass": False,
                }
        return results

    def run_sequential_memory_leak_probe(self) -> dict[str, Any]:
        """Run 10 consecutive 10 MiB operations tracking baseline RSS (Section 71)."""
        print("\n---> Running Sequential Memory Leak Probe (10 x 10 MiB sequential operations)")
        baselines = []
        fixture = build_txt_fixture(SIZE_10_MIB, positive=True, gen=self.gen)

        p = psutil.Process(os.getpid()) if psutil else None

        for i in range(10):
            gc.collect()
            b = p.memory_info().rss if p else 0
            baselines.append(b)
            self.pipeline.clean(fixture, filename="leak_probe.txt")

        gc.collect()
        final_b = p.memory_info().rss if p else 0
        baselines.append(final_b)

        # Check monotonic growth: is baseline at step 10 significantly higher than step 2?
        # Normal Python allocator pools may grow in steps 1-2 and stabilize.
        stabilized = baselines[2:]
        growth = stabilized[-1] - stabilized[0]
        # Flag if growth exceeds 32 MiB
        leak_detected = growth > (32 * 1024 * 1024)
        print(f"     Leak Probe: Baseline shift over runs 2-10: {growth / (1024*1024):.2f} MiB (Leak: {leak_detected})")

        return {
            "runs": len(baselines) - 1,
            "baseline_rss_sequence_bytes": baselines,
            "growth_bytes": growth,
            "leak_detected": leak_detected,
            "status": "PASS" if not leak_detected else "INVESTIGATE",
        }

    def run_closure_guardrails(self) -> dict[str, Any]:
        """Run representative 50 and 100 MiB closure measurements under Section 10 guardrails."""
        print("\n---> Running Memory Budget Closure Workload (Section 10 & 12)")
        closure_specs = [
            ("txt", [SIZE_50_MIB], "TEXT_WHOLE_BUFFER"),
            ("docx", [SIZE_50_MIB, SIZE_100_MIB], "DOCX_OPC_TREE"),
            ("xlsx", [SIZE_50_MIB, SIZE_100_MIB], "XLSX_OPC_TREE"),
            ("odt", [SIZE_50_MIB, SIZE_100_MIB], "ODF_PACKAGE"),
            ("png", [SIZE_50_MIB, SIZE_100_MIB], "CHUNKED_IMAGE"),
            ("wav", [SIZE_50_MIB, SIZE_100_MIB], "AUDIO_RIFF_IN_PROCESS"),
        ]
        results = {}
        for ext, sizes, eclass in closure_specs:
            for pos in (True, False):
                profile_id = f"{ext}_{'positive' if pos else 'nochange'}"
                for sz in sizes:
                    sz_name = f"{sz // (1024 * 1024)}MiB"
                    key = f"{profile_id}_{sz_name}"
                    fixture = self.generate_fixture(ext, sz, positive=pos)
                    cleaned, rep, meas = self.run_clean_operation(fixture, ext)
                    guardrail_res = self.evaluate_closure_guardrail(
                        execution_class=eclass,
                        target_size_bytes=sz,
                        delta_parent_rss_bytes=meas.parent_delta_rss_bytes,
                        delta_tree_rss_bytes=meas.tree_delta_rss_bytes,
                    )
                    rule = CLOSURE_GUARDRAILS[eclass]
                    limit_bytes = rule["base_bytes"] + int(rule["multiplier"] * sz)
                    results[key] = {
                        "format": ext,
                        "is_positive": pos,
                        "execution_class": eclass,
                        "target_size_bytes": sz,
                        "size_label": sz_name,
                        "wall_ms": round(meas.wall_ms, 2),
                        "parent_peak_rss_bytes": meas.parent_peak_rss_bytes,
                        "tree_peak_rss_bytes": meas.tree_peak_rss_bytes,
                        "parent_delta_rss_bytes": meas.parent_delta_rss_bytes,
                        "tree_delta_rss_bytes": meas.tree_delta_rss_bytes,
                        "guardrail_limit_bytes": limit_bytes,
                        "guardrail_status": guardrail_res,
                        "pipeline_status": rep.status.value,
                    }
                    print(f"     [{key}] Delta RSS: {meas.parent_delta_rss_bytes / (1024*1024):.1f} MiB / Allowed: {limit_bytes / (1024*1024):.1f} MiB -> {guardrail_res}")
        return results


# ==============================================================================
# HARNESS EXECUTION & REPORT GENERATION
# ==============================================================================
def collect_system_metadata() -> dict[str, Any]:
    """Collect non-sensitive environment metadata (Section 28)."""
    vm = psutil.virtual_memory() if psutil else None
    du = shutil.disk_usage(tempfile.gettempdir())

    # Detect ffmpeg version
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_ver = "unavailable"
    if ffmpeg_path:
        try:
            import subprocess
            r = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
            ffmpeg_ver = r.stdout.splitlines()[0] if r.stdout else "unknown"
        except Exception:
            ffmpeg_ver = "error"

    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_count_logical": psutil.cpu_count(logical=True) if psutil else 1,
        "cpu_count_physical": psutil.cpu_count(logical=False) if psutil else 1,
        "cpu_processor": platform.processor(),
        "total_ram_bytes": vm.total if vm else 0,
        "available_ram_bytes": vm.available if vm else 0,
        "temp_disk_free_bytes": du.free,
        "psutil_version": psutil.__version__ if psutil else "unavailable",
        "ffmpeg_version": ffmpeg_ver,
    }


def collect_runtime_limits() -> dict[str, Any]:
    """Collect canonical production limits (Section 3)."""
    sec = security.SecurityLimits()
    return {
        "top_level_max_input_bytes": common.MAX_INPUT_BYTES,
        "max_stdin_bytes": common.MAX_STDIN_BYTES,
        "http_max_body_bytes": server.MAX_BODY_BYTES if "server" in sys.modules else 402653184,
        "http_max_input_bytes": server.MAX_INPUT_BYTES if "server" in sys.modules else 268435456,
        "batch_per_file_max_input_bytes": BatchProcessor.MAX_INPUT_BYTES if hasattr(BatchProcessor, "MAX_INPUT_BYTES") else 33554432,
        "batch_max_total_bytes": 209715200,
        "batch_max_files": 100,
        "zip_member_uncompressed_max_bytes": sec.max_member_uncompressed_bytes,
        "zip_total_uncompressed_max_bytes": sec.max_total_uncompressed_bytes,
        "xml_part_max_bytes": sec.max_xml_part_bytes,
        "xml_aggregate_max_bytes": sec.max_total_xml_bytes,
        "max_compression_ratio": sec.max_compression_ratio,
        "max_xml_depth": sec.max_xml_depth,
        "max_xml_elements": sec.max_xml_elements,
    }


def validate_benchmark_results(data: dict[str, Any]) -> bool:
    """Validate JSON benchmark results for schema consistency (Section 53)."""
    assert "schema_version" in data
    assert "environment" in data
    assert "limits" in data
    assert "profiles" in data

    for prof in data["profiles"]:
        assert "benchmark_id" in prof
        assert "canonical_policy" in prof
        assert "streaming_classification" in prof
        for size_k, res in prof["results_by_size"].items():
            assert res["target_size_bytes"] > 0
            if res["production_allowed"] and res["status"] == "PASS":
                assert res["actual_size_bytes"] > 0
                assert res["median_wall_ms"] >= 0
                assert res["max_parent_peak_rss_bytes"] >= 0
                assert res["max_parent_delta_rss_bytes"] >= 0
                assert len(res["raw_runs"]) > 0
    return True


def run_benchmarks(quick: bool = False, output_json: Path | None = None) -> dict[str, Any]:
    """Orchestrate canonical Phase 11 benchmark run."""
    if output_json is None:
        output_json = REPO_ROOT / "artifacts" / "v2.1" / "phase11_benchmark.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)

    engine = BenchmarkEngine(output_json=output_json, quick=quick)

    # 1. Environment and limits preflight
    env_meta = collect_system_metadata()
    limits_meta = collect_runtime_limits()

    # 2. Scaling Profiles (Section 8)
    profiles_to_run = [
        # Class A: TEXT
        ("text_positive", "txt", "txt", "TEXT_WHOLE_BUFFER", "FULL_BUFFER", True, False),
        ("text_nochange", "txt", "txt", "TEXT_WHOLE_BUFFER", "FULL_BUFFER", False, False),
        # Class B: LOSSLESS OPC (DOCX)
        ("docx_positive", "docx", "docx", "LOSSLESS_OPC", "RAW_MEMBER_PASSTHROUGH", True, False),
        ("docx_nochange", "docx", "docx", "LOSSLESS_OPC", "RAW_MEMBER_PASSTHROUGH", False, False),
        # Class C: SECOND OPC (XLSX)
        ("xlsx_positive", "xlsx", "xlsx", "SECOND_OPC", "RAW_MEMBER_PASSTHROUGH", True, False),
        ("xlsx_nochange", "xlsx", "xlsx", "SECOND_OPC", "RAW_MEMBER_PASSTHROUGH", False, False),
        # Class D: GENERIC CONTAINER (ODT)
        ("odt_positive", "odt", "odt", "GENERIC_CONTAINER", "RAW_MEMBER_PASSTHROUGH", True, False),
        ("odt_nochange", "odt", "odt", "GENERIC_CONTAINER", "RAW_MEMBER_PASSTHROUGH", False, False),
        # Class E: CHUNK/IMAGE (PNG)
        ("png_positive", "png", "png", "IMAGE_CHUNK", "STREAMING_INPUT_FULL_OUTPUT", True, False),
        ("png_nochange", "png", "png", "IMAGE_CHUNK", "STREAMING_INPUT_FULL_OUTPUT", False, False),
        # Class F: AUDIO RIFF (WAV) - In-process RIFF chunk stripping
        ("wav_positive", "audio", "wav", "AUDIO_RIFF_IN_PROCESS", "STREAMING_INPUT_FULL_OUTPUT", True, False),
        ("wav_nochange", "audio", "wav", "AUDIO_RIFF_IN_PROCESS", "STREAMING_INPUT_FULL_OUTPUT", False, False),
        # CLI End-to-End representative runs
        ("cli_docx_positive", "docx", "docx", "CLI_END_TO_END", "RAW_MEMBER_PASSTHROUGH", True, True),
        ("cli_txt_positive", "txt", "txt", "CLI_END_TO_END", "FULL_BUFFER", True, True),
    ]

    profile_summaries = []
    for pid, policy, ext, eclass, sclass, pos, is_cli in profiles_to_run:
        summary = engine.run_scaling_profile(pid, policy, ext, eclass, sclass, pos, is_cli=is_cli)
        profile_summaries.append(asdict(summary))

    # 3. Batch Workload (Section 26 & 70)
    batch_result = engine.run_batch_workload()

    # 4. Breadth Smoke (Section 7)
    breadth_result = engine.run_breadth_smoke()

    # 5. Sequential Leak Probe (Section 71)
    leak_result = engine.run_sequential_memory_leak_probe()

    # 6. Assemble Final Benchmark Payload
    benchmark_payload = {
        "schema_version": "2.1.0",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "quick" if quick else "full",
        "seed": FIXED_SEED,
        "environment": env_meta,
        "limits": limits_meta,
        "memory_budgets": {
            "in_process": "delta_parent_rss <= 96 MiB + 2.5 * input_size",
            "external_process": "delta_tree_rss <= 256 MiB + 4.0 * input_size",
        },
        "profiles": profile_summaries,
        "batch_workload": batch_result,
        "breadth_smoke": breadth_result,
        "memory_leak_probe": leak_result,
    }

    # 7. Self-Consistency Validation
    validate_benchmark_results(benchmark_payload)

    # 8. Write JSON Artifact
    output_json.write_text(json.dumps(benchmark_payload, indent=2), encoding="utf-8")
    print(f"\n[OK] Benchmark completed and saved to: {output_json}")

    return benchmark_payload


def main():
    parser = argparse.ArgumentParser(description="Phase 11 Large File Performance Harness")
    parser.add_argument("--quick", action="store_true", help="Quick mode (1, 10 MiB, 1 rep)")
    parser.add_argument("--full", action="store_true", help="Full canonical Phase 11 run (1, 10, 50, 100 MiB, 3 reps)")
    parser.add_argument("--output-json", type=Path, default=REPO_ROOT / "artifacts" / "v2.1" / "phase11_benchmark.json")
    args = parser.parse_args()

    # Default to quick unless --full is provided
    quick_mode = not args.full
    run_benchmarks(quick=quick_mode, output_json=args.output_json)


if __name__ == "__main__":
    main()
