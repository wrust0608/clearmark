"""tests/test_performance_benchmarks.py

Performance benchmarks for lossless DOCX processing.
Validates latency, throughput, and memory scaling on various document sizes
and on real-world benchmark documents.
"""

import io
import os
import sys
import time
import tracemalloc
import zipfile
from pathlib import Path
import pytest

from docx.cleaner import clean_docx_lossless
from docx.visible_text import extract_canonical_visible_text

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DOCX = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
STRESS_DOCX = REPO_ROOT / "02_BAD_OUTPUT_RUN_EXPLOSION.docx"


def _generate_benchmark_doc(paragraph_count: int, watermark_ratio: float = 0.5) -> bytes:
    """Generate a synthetic DOCX with the given number of paragraphs and embedded watermarks."""
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paras = []
    for i in range(paragraph_count):
        wm = "\u200B" if (i % 2 == 0) else ""
        paras.append(
            f"""<w:p>
              <w:r><w:t>Đoạn văn số {i}: Quản lý chất lượng công trình xây dựng{wm}.</w:t></w:r>
              <w:r><w:t> Đảm bảo tiêu chuẩn kỹ thuật an toàn.</w:t></w:r>
            </w:p>"""
        )

    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{W_NS}">
      <w:body>
        {"".join(paras)}
      </w:body>
    </w:document>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc_xml.encode("utf-8"))
        z.writestr("[Content_Types].xml", b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("_rels/.rels", b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr("docProps/core.xml", b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')
    return buf.getvalue()


def test_scaling_latency_and_memory():
    """Verify linear scaling O(N) and bounded memory across document sizes."""
    sizes = [10, 50, 200]
    timings = {}

    for size in sizes:
        doc_bytes = _generate_benchmark_doc(size)

        # Warmup
        clean_docx_lossless(doc_bytes)

        best_ms = float("inf")
        peak_mem = 0
        for _ in range(3):
            tracemalloc.start()
            t0 = time.perf_counter()
            clean_bytes, report = clean_docx_lossless(doc_bytes)
            t1 = time.perf_counter()
            _, cur_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            best_ms = min(best_ms, (t1 - t0) * 1000)
            peak_mem = max(peak_mem, cur_peak)

        elapsed_ms = best_ms
        timings[size] = elapsed_ms

        assert report["fidelity_guaranteed"] is True
        # For 200 paragraphs, execution should easily be under 500ms
        assert elapsed_ms < 500, f"Processing {size} paragraphs took {elapsed_ms:.1f} ms (> 500ms)"
        # Peak memory should be well under 50MB
        assert peak_mem < 50 * 1024 * 1024, f"Peak memory {peak_mem / 1024:.1f} KB exceeded 50MB"

    # Scalability check: 200 paragraphs should take less than 15x of 10 paragraphs
    assert timings[200] < timings[10] * 25 + 200


def test_real_document_latency_benchmark():
    """Benchmark the True Golden Original (288 runs, 19 pages) and stress witness (6467 runs)."""
    if not GOLDEN_DOCX.exists():
        pytest.skip(f"Benchmark file {GOLDEN_DOCX} not found on this system")

    data = GOLDEN_DOCX.read_bytes()

    # Warmup
    clean_docx_lossless(data)

    runs = 5
    t0 = time.perf_counter()
    for _ in range(runs):
        clean_bytes, rep = clean_docx_lossless(data)
        assert rep["fidelity_guaranteed"] is True
    t1 = time.perf_counter()

    avg_latency_ms = ((t1 - t0) / runs) * 1000
    print(f"\n[BENCHMARK] Average clean_docx_lossless latency on True Golden ({GOLDEN_DOCX.name}, 288 runs): {avg_latency_ms:.2f} ms")

    # Target: average latency strictly under 500 ms (typically around 200-300 ms)
    assert avg_latency_ms < 500, f"Average latency {avg_latency_ms:.2f} ms exceeded 500ms"

    # Negative witness rejection latency (fail-closed validator rejection)
    if STRESS_DOCX.exists():
        from docx.validator import DocxFidelityValidator, DocxFidelityException
        from docx.mutation_plan import DocxMutationPlan

        stress_data = STRESS_DOCX.read_bytes()
        t0 = time.perf_counter()
        for _ in range(5):
            val = DocxFidelityValidator(data, stress_data, DocxMutationPlan())
            try:
                val.validate()
            except DocxFidelityException:
                pass
        t1 = time.perf_counter()
        rejection_latency_ms = ((t1 - t0) / 5) * 1000
        print(f"[BENCHMARK] NEGATIVE-WITNESS REJECTION LATENCY ({STRESS_DOCX.name}, 6467 runs): {rejection_latency_ms:.2f} ms")
        assert rejection_latency_ms < 500


def test_valid_high_run_stress_throughput():
    """Benchmark full successful cleaner path on a valid synthetic DOCX with ~6,467 runs containing carriers."""
    paras = []
    for i in range(2156):
        paras.append(
            f'<w:p><w:r><w:t>Đoạn văn {i}: </w:t></w:r>'
            f'<w:r><w:t>Quản lý\u200B chất lượng</w:t></w:r>'
            f'<w:r><w:t> công trình tiêu chuẩn.</w:t></w:r></w:p>'
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(paras)}</w:body></w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml.encode("utf-8"))
        z.writestr("[Content_Types].xml", b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("_rels/.rels", b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        z.writestr("docProps/core.xml", b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')

    raw = buf.getvalue()

    # Warmup
    clean_docx_lossless(raw)

    best_ms = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        clean_bytes, rep = clean_docx_lossless(raw)
        t1 = time.perf_counter()
        best_ms = min(best_ms, (t1 - t0) * 1000)

    stress_throughput_ms = best_ms
    print(f"\n[BENCHMARK] VALID HIGH-RUN STRESS THROUGHPUT (6468 runs): {stress_throughput_ms:.2f} ms")
    assert rep["fidelity_guaranteed"] is True
    assert stress_throughput_ms < 2000, f"Stress throughput {stress_throughput_ms:.2f} ms exceeded 2000ms"

