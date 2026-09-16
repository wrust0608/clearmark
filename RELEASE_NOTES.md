# RELEASE NOTES: LOSSLESS WATERMARK REMOVAL v2.0.0

> **Subsystem**: Lossless DOCX Subsystem & Document Fidelity Engine  
> **Trạng thái**: FINAL RELEASE APPROVED (v2.0.0)  
> **Local fork release**: `v2.0.0`  
> **Upstream latest release**: `v0.7.0`  
> **Authoritative True Golden Baseline**: `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`  
> **Valid Candidate Output**: `04_CANDIDATE_LOSSLESS_OUTPUT.docx`  
> **Cổng dịch vụ mặc định**: `8765` (`http://127.0.0.1:8765` / `http://localhost:8765`)

---

## 1. Mục tiêu Bản Phát hành v2.0.0

Bản phát hành v2.0.0 giải quyết dứt điểm sự cố suy giảm chất lượng tài liệu (word gluing / run explosion / paraphrasing) trong các phiên bản trước đây bằng cách thay thế toàn bộ pipeline xử lý DOCX cũ bằng kiến trúc **Lossless DOCX Subsystem**.

### Cam kết Cốt lõi:
1. **Tuyệt đối không sửa đổi văn bản nhìn thấy** (Zero Paraphrasing / Zero Hallucination).
2. **Không làm dính chữ / vỡ từ** (Bảo toàn hoàn hảo `xml:space="preserve"` và Run boundaries).
3. **Bảo tồn nguyên vẹn 100% cấu trúc OOXML không mục tiêu** (Tables, Drawings, Bookmarks, Page Breaks, Header/Footer, Sections).
4. **Không phụ thuộc mạng ngoài**: DOCX Safe/Lossless cleaning pipeline performs entirely locally and does not make network requests (`DOCX_SAFE_ZERO_EGRESS = PASS`).

---

## 2. So sánh Kiến Trúc Trước và Sau Refactor

| Đặc tính | Kiến trúc cũ (Trước Refactor) | Kiến trúc mới (Lossless Subsystem) |
| :--- | :--- | :--- |
| **Mô hình xử lý** | `PARSE -> NORMALIZE -> REBUILD` *(Phá hủy cấu trúc)* | `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT` *(Bảo toàn)* |
| **Can thiệp tệp ZIP** | Giải nén toàn bộ ra đĩa, tạo lại ZIP mới làm mất attributes, timestamps, member order | Byte-safe in-memory rebuild; giữ nguyên 100% member order, compression flags, non-target hashes |
| **Xử lý văn bản DOCX** | Gộp toàn bộ text trong paragraph, strip space, gọi LLM paraphrase | Xác định vị trí từng ký tự carrier ở cấp độ Run; chỉ thay thế tối thiểu ký tự ẩn mục tiêu |
| **Bảo toàn khoảng trắng** | Dùng heuristic regex chèn space (dẫn đến dính chữ / ngắt dòng sai) | Tự động bổ sung `xml:space="preserve"` trên thẻ `<w:t>`, giữ nguyên Run boundary |
| **Bảo vệ đối tượng Word** | Bị xóa hoặc mất liên kết (tables, drawings, bookmarks, field codes) | Bất biến 100%: Tables, DrawingML, Math equations, Track changes, Bookmarks được bảo vệ tuyệt đối |
| **Thời gian xử lý (19 trang)** | 1 - 3 phút (chờ LLM local/remote sinh văn bản) | **Median 231.12 ms** (p95: 235.52 ms), Peak RAM: 4.79 MB |
| **Cơ chế dự phòng lỗi** | Xuất file hỏng nếu có lỗi (Fail-open) | **Fail-closed**: Tự động rollback về bản gốc 100% nếu phát hiện sai lệch dù chỉ 1 ký tự |
| **Quyền riêng tư (Privacy)** | Cần chạy mô hình AI lớn hoặc gọi API ngoài | DOCX Safe/Lossless cleaning pipeline performs entirely locally and does not make network requests. *(Optional remote text rewrite backends for supported plain-text workflows may use the network only when explicitly enabled by the user).* |

---

## 3. Kết quả nghiệm thu trên True Golden Original (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`)

- **Khóa mật mã học (SHA-256)**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d`
- **Dung lượng**: 49,959 bytes (Gốc) $\rightarrow$ 49,395 bytes (`04_CANDIDATE_LOSSLESS_OUTPUT.docx`, SHA-256: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297`).  
  *(RC1 historical candidate — superseded: 45,633 bytes, SHA-256: `f7d770df334380cc03e9a224fe1a499804d5b4868637683cc1afeaf712e67340`).*
- **Tính đồng nhất văn bản nhìn thấy**: **100.000% EXACT** (`visible_text_exact = True`).
- **Delta cấu trúc & Invariants**:
  - Paragraphs: $204 \rightarrow 204$ (Delta = 0).
  - Runs: $288 \rightarrow 288$ (Delta = 0, **0 run explosion**).
  - Manual Page Breaks: $5 \rightarrow 5$ (Delta = 0, **0 page break loss**).
  - Tables: $1 \rightarrow 1$ (Delta = 0).
  - Table Rows: $7 \rightarrow 7$ (Delta = 0).
  - Table Cells: $49 \rightarrow 49$ (Delta = 0).
  - Sections: $1 \rightarrow 1$ (Delta = 0).
  - ZIP Members: $15 \rightarrow 15$ (Delta = 0).
  - LibreOffice Rendered Pages: $19 \rightarrow 19$ (Delta = 0).
- **Strict Non-Target Raw ZIP Preservation**:
  - 13/13 non-target members có mã băm giải nén (uncompressed SHA-256) **bit-for-bit SAME** (bao gồm cả `word/document.xml`).
  - 13/13 non-target members có mã băm nén thô (raw compressed payload SHA-256) **bit-for-bit SAME** nhờ Raw OPC ZIP Copier pass-through.
  - Bảo tồn nguyên vẹn local file header, metadata (`flag_bits = 6`, `external_attr = 0`), và OPC alignment extra padding.
  - 13/13 non-target members: uncompressed payload SAME, compressed payload SAME, CRC SAME, compress_type SAME, flag_bits SAME, external_attr SAME, internal_attr SAME, date_time SAME, extra SAME, comment SAME.
  - Chỉ 2 members metadata mục tiêu (`docProps/core.xml` & `docProps/app.xml`) thay đổi theo Mutation Plan.
- **Visual Regression (LibreOffice Headless + Pixel Comparison)**:
  - 19/19 trang đạt **100% Pixel Identity (similarity = 1.0)**.
- **Negative Witnesses Failure (Fail-Closed Rejection)**:
  - `02_BAD_OUTPUT_RUN_EXPLOSION.docx` $\rightarrow$ **FAIL** (runs 288 -> 6467, page breaks 5 -> 4, text regression).
  - `03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION.docx` $\rightarrow$ **FAIL** (runs 288 -> 6467, page breaks 5 -> 4, pages 19 -> 18).
- **Hiệu năng Thực tế & Độ trễ (Performance Benchmarks)**:
  - Document: `01_GOLDEN_ORIGINAL_UNTOUCHED.docx` (49,959 bytes, 288 runs, 19 trang)
  - **True Golden Median Latency**: **231.12 ms** (ngưỡng chấp nhận < 500 ms)
  - **P95 Latency**: **235.52 ms**
  - **Peak Memory**: **4.79 MB** (ngưỡng chấp nhận < 35 MB)
  - **NEGATIVE-WITNESS REJECTION LATENCY (`02_BAD_OUTPUT_RUN_EXPLOSION.docx`, 6,467 runs)**: Median latency = 62.39 ms (bị chặn sớm và an toàn bởi validator)
  - **VALID HIGH-RUN STRESS THROUGHPUT (Synthetic DOCX, 6,468 runs with carriers)**: Throughput latency = 169.16 ms (`fidelity_guaranteed = True`)
- **Toàn bộ Test Suite Repository (Full Pytest Canonical Run)**:
  - **1359 passed, 0 failed, 152 skipped** (duration 63.76s).
  - Subsystem tests (122/122 tests) là tập con đạt 100% PASS.

> [!NOTE]
> **Lưu ý Tài liệu Thực tế (Real Document Note)**: Trên mẫu chuẩn `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`, `word/document.xml` là byte-identical trước và sau khi làm sạch. Hai part thay đổi duy nhất là metadata provenance (`docProps/core.xml` xóa `cp:lastModifiedBy` và `docProps/app.xml` xóa `Application`). Do đó, mẫu này minh chứng cho tính toàn vẹn tài liệu và khả năng tẩy sạch metadata. Khả năng gỡ bỏ ký tự Unicode carrier trong phần thân được kiểm chứng độc lập thông qua bộ synthetic/regression fixtures chuyên dụng.

> [!IMPORTANT]
> **Giới hạn Kỹ thuật & Ranh giới Fail-Closed (Technical Limitations)**:  
> The strict raw OPC copier currently supports the ZIP forms used by standard Word DOCX fixtures in the validated test matrix, including STORED and DEFLATED entries. Unsupported or unvalidated ZIP features must fail closed, including where applicable:
> - ZIP64 edge cases
> - multi-disk archives
> - unsupported compression algorithms
> - encrypted ZIP members
> Do not silently normalize unsupported archive structures.

---

## 4. Hướng dẫn Khởi chạy & Vận hành

### Khởi chạy một chạm (Khuyến nghị cho người dùng Windows)
Chỉ cần nhấp đúp chuột vào tệp:
```bat
ClearMark.cmd
```
Hệ thống sẽ tự động khởi tạo môi trường Python cục bộ siêu tốc, mở Web UI tại `http://127.0.0.1:8765` (hoặc `http://localhost:8765`), và sẵn sàng xử lý tệp tin với độ tin cậy tuyệt đối.

### Khởi chạy qua PowerShell CLI
```powershell
.\clearmark-manager.ps1 -Action start -Port 8765
```

### Sử dụng công cụ dòng lệnh (CLI Tool)
```bash
uv run python service/scripts/container_meta.py clean "tai_lieu.docx" -o "tai_lieu_clean.docx"
```

### Kiểm tra độ trung thực của tài liệu (Fidelity Verification CLI)
```bash
uv run python tools/verify_document_fidelity.py 01_GOLDEN_ORIGINAL_UNTOUCHED.docx --candidate 04_CANDIDATE_LOSSLESS_OUTPUT.docx --out-json artifacts/real_document_fidelity_report_v2.json
```

---

## 5. Kết luận & Nghiệm thu Bàn giao

Hệ thống đã vượt qua toàn bộ các kiểm thử nghiêm ngặt trên True Golden Baseline, với validator fail đúng trên 2 negative witnesses và candidate output đạt chuẩn lossless tuyệt đối. Ứng dụng đã sẵn sàng vận hành chính thức trong môi trường người dùng cuối.

- Báo cáo Nghiệm thu Chi tiết: [`docs/reports/MASTER_REVALIDATION_REPORT.md`](docs/reports/MASTER_REVALIDATION_REPORT.md)
- Trung tâm Tài liệu & Báo cáo: [`docs/README.md`](docs/README.md)
- Dữ liệu Kiểm toán Máy đọc: [`artifacts/README.md`](artifacts/README.md)
- Gói Bằng chứng Nghiệm thu Cuối cùng: [`artifacts/final_acceptance/`](artifacts/final_acceptance/)
