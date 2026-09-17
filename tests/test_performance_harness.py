"""Unit tests for Phase 11 Large File Performance Harness (tests/test_performance_harness.py).

Validates:
1. Deterministic data generator sizing and reproducibility.
2. JSON schema validator consistency (Section 53).
3. Median and throughput calculations (Section 17, 27).
4. Budget evaluation logic (Section 33).
5. Resource limit classifications (Section 4, 26).
6. Fixture generation reproducibility across repeated runs (Section 59).
7. Quick mode engine smoke execution and cleanup.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Add repo root and service/scripts to path
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

for p in (SCRIPTS_DIR, BENCHMARKS_DIR, REPO_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from bench_large_files import (
    FIXED_SEED,
    SIZE_1_MIB,
    SIZE_10_MIB,
    SIZE_50_MIB,
    SIZE_100_MIB,
    BenchmarkEngine,
    DeterministicDataGenerator,
    collect_runtime_limits,
    collect_system_metadata,
    validate_benchmark_results,
)
import common
import security
from pipeline_types import ErrorCode


def test_deterministic_generator_sizing():
    """Generator must produce exact byte count requested with low compressibility."""
    gen1 = DeterministicDataGenerator(seed=FIXED_SEED)
    b100 = gen1.generate_bytes(100)
    assert len(b100) == 100
    assert any(b != 0 for b in b100)

    # 1 MiB generation check
    gen2 = DeterministicDataGenerator(seed=FIXED_SEED)
    b1m = gen2.generate_bytes(SIZE_1_MIB)
    assert len(b1m) == SIZE_1_MIB


def test_deterministic_generator_reproducibility():
    """Two generators initialized with identical seed must yield byte-identical outputs."""
    gen1 = DeterministicDataGenerator(seed=0x12345678)
    gen2 = DeterministicDataGenerator(seed=0x12345678)

    chunk1 = gen1.generate_bytes(131072)
    chunk2 = gen2.generate_bytes(131072)

    assert hashlib.sha256(chunk1).hexdigest() == hashlib.sha256(chunk2).hexdigest()


def test_fixture_reproducibility(tmp_path):
    """Generated test fixtures of same profile and size must have identical SHA256 hashes."""
    engine = BenchmarkEngine(output_json=tmp_path / "bench.json", quick=True)
    f1 = engine.generate_fixture("txt", SIZE_1_MIB, positive=True)
    h1 = hashlib.sha256(f1).hexdigest()

    f2 = engine.generate_fixture("txt", SIZE_1_MIB, positive=True)
    h2 = hashlib.sha256(f2).hexdigest()

    assert h1 == h2
    assert len(f1) == SIZE_1_MIB


def test_median_and_throughput():
    """Median wall time and throughput calculations must be mathematically exact."""
    engine = BenchmarkEngine(quick=True)

    # Median of odd count
    m1 = engine.compute_median([100.0, 120.0, 110.0])
    assert m1 == 110.0

    # Median of even count
    m2 = engine.compute_median([100.0, 110.0])
    assert m2 == 105.0

    # Throughput: 10 MiB in 100 ms (0.1 s) -> 100 MiB/s
    tp = engine.compute_throughput(SIZE_10_MIB, 100.0)
    assert abs(tp - 100.0) < 1e-4

    # Guard zero wall_time
    assert engine.compute_throughput(SIZE_10_MIB, 0.0) == 0.0


def test_budget_evaluation():
    """Predeclared memory budgets must correctly flag compliant vs exceeding runs."""
    engine = BenchmarkEngine(quick=True)

    # In-process: delta_parent <= 96 MiB + 2.5 * size
    # For 10 MiB, allowed = 96 + 25 = 121 MiB
    assert engine.evaluate_budget(
        execution_class="TEXT_WHOLE_BUFFER",
        target_size_bytes=SIZE_10_MIB,
        delta_parent_rss_bytes=50 * 1024 * 1024,
        delta_tree_rss_bytes=50 * 1024 * 1024,
    ) == "PASS"

    assert engine.evaluate_budget(
        execution_class="TEXT_WHOLE_BUFFER",
        target_size_bytes=SIZE_10_MIB,
        delta_parent_rss_bytes=150 * 1024 * 1024,
        delta_tree_rss_bytes=150 * 1024 * 1024,
    ) == "INVESTIGATE"

    # External AV: delta_tree <= 256 MiB + 4.0 * size
    # For 50 MiB, allowed = 256 + 200 = 456 MiB
    assert engine.evaluate_budget(
        execution_class="EXTERNAL_AV",
        target_size_bytes=SIZE_50_MIB,
        delta_parent_rss_bytes=30 * 1024 * 1024,
        delta_tree_rss_bytes=300 * 1024 * 1024,
    ) == "PASS"

    assert engine.evaluate_budget(
        execution_class="EXTERNAL_AV",
        target_size_bytes=SIZE_50_MIB,
        delta_parent_rss_bytes=30 * 1024 * 1024,
        delta_tree_rss_bytes=500 * 1024 * 1024,
    ) == "INVESTIGATE"


def test_limit_classification():
    """Limits must accurately classify allowed sizes and expected rejections."""
    sec = security.SecurityLimits()

    # Canonical input limit: 256 MiB
    assert SIZE_1_MIB <= common.MAX_INPUT_BYTES
    assert SIZE_10_MIB <= common.MAX_INPUT_BYTES
    assert SIZE_50_MIB <= common.MAX_INPUT_BYTES
    assert SIZE_100_MIB <= common.MAX_INPUT_BYTES

    # Member uncompressed limit: 64 MiB
    assert SIZE_1_MIB <= sec.max_member_uncompressed_bytes
    assert SIZE_10_MIB <= sec.max_member_uncompressed_bytes
    assert SIZE_50_MIB <= sec.max_member_uncompressed_bytes
    # 100 MiB single member uncompressed is NOT allowed unless split
    assert SIZE_100_MIB > sec.max_member_uncompressed_bytes

    # Total uncompressed limit: 128 MiB
    assert SIZE_100_MIB <= sec.max_total_uncompressed_bytes


def test_schema_validator_consistency():
    """validate_benchmark_results must enforce self-consistency requirements."""
    valid_payload = {
        "schema_version": "2.1.0",
        "environment": {"os": "Windows"},
        "limits": {"max_input_bytes": 268435456},
        "profiles": [
            {
                "benchmark_id": "text_positive",
                "canonical_policy": "txt",
                "streaming_classification": "FULL_BUFFER",
                "results_by_size": {
                    "1_mib": {
                        "target_size_bytes": SIZE_1_MIB,
                        "actual_size_bytes": SIZE_1_MIB,
                        "production_allowed": True,
                        "status": "PASS",
                        "median_wall_ms": 15.2,
                        "max_parent_peak_rss_bytes": 50000000,
                        "max_parent_delta_rss_bytes": 2000000,
                        "raw_runs": [{"wall_ms": 15.2, "parent_peak_rss_bytes": 50000000}],
                    }
                },
            }
        ],
    }
    assert validate_benchmark_results(valid_payload) is True

    # Missing profile fields must fail assertion
    bad_payload = {"schema_version": "2.1.0", "environment": {}, "limits": {}, "profiles": [{}]}
    with pytest.raises(AssertionError):
        validate_benchmark_results(bad_payload)


def test_quick_mode_single_profile_smoke(tmp_path):
    """Run a single 1 MiB TXT profile in engine to verify timing and memory sampling."""
    json_path = tmp_path / "smoke.json"
    engine = BenchmarkEngine(output_json=json_path, quick=True)
    engine.sizes = [SIZE_1_MIB]

    summary = engine.run_scaling_profile(
        benchmark_id="text_smoke",
        canonical_policy="txt",
        ext="txt",
        exec_class="TEXT_WHOLE_BUFFER",
        streaming_class="FULL_BUFFER",
        positive=True,
        is_cli=False,
    )

    assert summary.benchmark_id == "text_smoke"
    assert "1MiB" in summary.results_by_size
    res1 = summary.results_by_size["1MiB"]
    assert res1.status == "PASS"
    assert res1.median_wall_ms > 0
    assert res1.throughput_mib_s > 0
    assert res1.idempotence_pass is True
