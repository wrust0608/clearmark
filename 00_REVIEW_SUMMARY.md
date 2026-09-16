# 00_REVIEW_SUMMARY: LOSSLESS DOCX ENGINE v2.0.0-RC2

> **Tài liệu hướng dẫn thẩm định dành cho Independent Reviewer & Auditor**  
> Bản phát hành: `v2.0.0-RC2`  
> Trạng thái: **RELEASE CANDIDATE APPROVED**

---

## 1. Thông Tin Tổng Quan Dự Án

- **PROJECT**: `watermarks-remover` local fork (Vietnamese Lossless DOCX Subsystem)
- **LOCAL FORK RELEASE CANDIDATE**: `v2.0.0-RC2` (RELEASE CANDIDATE APPROVED)
- **UPSTREAM LATEST RELEASE**: `v0.7.0` (guillaumemeyer/watermarks-remover)
- **DEFAULT SERVICE PORT**: `8765` (`http://127.0.0.1:8765` / `http://localhost:8765`)

---

## 2. Kiến Trúc Cốt Lõi (Architecture)

Kiến trúc cũ phá hủy cấu trúc (`PARSE -> NORMALIZE -> REBUILD`) đã bị loại bỏ hoàn toàn.
Hệ thống vận hành theo nguyên tắc **Lossless Invariant Preservation**:

```
DETECT
  └── Quét và phát hiện chính xác các ký tự carrier ẩn & metadata provenance
-> PLAN
  └── Lập Mutation Plan bất biến, xác định rõ các node và part mục tiêu
-> MINIMAL PATCH
  └── Thao tác thay thế tối thiểu in-memory, bảo toàn tuyệt đối xml:space="preserve"
-> VALIDATE
  └── Khung kiểm chứng 4 tầng Fail-Closed thời gian chạy (Package, Hash, Canonical Text, Structure)
-> OUTPUT
  └── Xuất tệp tin làm sạch hoàn hảo (Rollback trả về bản gốc nếu sai lệch dù 1 ký tự)
```
*(Ghi chú: Khung thẩm định mở rộng áp dụng thêm 5 quality gates gồm formatting fingerprints, rendered page count, và visual pixel comparisons).*

---

## 3. Khóa Mật Mã Học: True Golden vs Valid Candidate

### TRUE GOLDEN BASELINE (Mẫu chuẩn nguyên bản bất biến):
- **filename**: `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`
- **size**: `49,959 bytes`
- **sha256**: `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d`
- **paragraphs**: 204
- **runs**: 288
- **manual_page_breaks**: 5
- **tables**: 1 (rows: 7, cells: 49)
- **sections**: 1
- **rendered_pages**: 19

### VALID CANDIDATE OUTPUT (Kết quả xử lý lossless được phê duyệt):
- **filename**: `04_CANDIDATE_LOSSLESS_OUTPUT.docx`
- **size**: `49,395 bytes`
- **sha256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297`

> [!NOTE]
> **Lưu ý Tài liệu Thực tế (Real Document Note)**: Trên mẫu chuẩn thực tế `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`, `word/document.xml` là byte-identical trước và sau khi làm sạch. Hai part thay đổi duy nhất là metadata provenance (`docProps/core.xml` xóa `cp:lastModifiedBy` và `docProps/app.xml` xóa `Application`). Do đó, mẫu này minh chứng cho tính toàn vẹn tài liệu và khả năng tẩy sạch metadata. Khả năng gỡ bỏ ký tự Unicode carrier trong phần thân được kiểm chứng độc lập thông qua bộ synthetic/regression fixtures chuyên dụng.

---

## 4. Kết Quả Nghiệm Thu Thống Kê & Bất Biến Cấu Trúc (RESULT)

| Tiêu chí | Trước xử lý (Golden) | Sau xử lý (Candidate) | Sai lệch ($\Delta$) | Trạng thái |
| :--- | :---: | :---: | :---: | :---: |
| **Paragraphs** | 204 | 204 | 0 | **PASS** |
| **Runs** | 288 | 288 | 0 (0 run explosion) | **PASS** |
| **Manual Page Breaks** | 5 | 5 | 0 (0 lost breaks) | **PASS** |
| **Rendered Pages** | 19 | 19 | 0 (0 lost pages) | **PASS** |
| **Tables** | 1 | 1 | 0 | **PASS** |
| **Table Rows** | 7 | 7 | 0 | **PASS** |
| **Table Cells** | 49 | 49 | 0 | **PASS** |
| **Sections** | 1 | 1 | 0 | **PASS** |
| **Visible Text Exact** | 100.000% | 100.000% | 0 | **PASS** |
| **Non-Target OOXML Hashes (Uncompressed)** | 13/13 members | 13/13 identical | 0 byte diff | **PASS** |
| **Non-Target Raw Compressed Payload Hashes** | 13/13 members | 13/13 identical | 0 byte diff | **PASS** |
| **OPC Raw Metadata (flag_bits, external_attr)** | flag_bits=6, attr=0 | flag_bits=6, attr=0 | 0 delta | **PASS** |
| **Visual Regression (Pixel Comparison)** | 19/19 trang | Similarity = 1.0 | 0 diff | **PASS** |

### Đo Lường Hiệu Năng & Độ Trễ (Performance Benchmarks):
- **True Golden Latency (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`, 288 runs)**:
  - **Median Latency**: `231.12 ms` (vượt xa mục tiêu < 500 ms)
  - **P95 Latency**: `235.52 ms`
  - **Peak Memory**: `4.79 MB` (ngưỡng an toàn < 35 MB)
- **NEGATIVE-WITNESS REJECTION LATENCY (`02_BAD_OUTPUT_RUN_EXPLOSION.docx`, 6,467 runs)**:
  - **Median Latency**: `62.39 ms` (Bị chặn sớm bởi Fail-Closed Validator do run explosion 288 -> 6467)
- **VALID HIGH-RUN STRESS THROUGHPUT (Synthetic DOCX, 6,468 runs with carriers)**:
  - **Latency**: `169.16 ms` (Xử lý thành công toàn bộ pipeline, `fidelity_guaranteed = True`)

### Kiểm Thử Toàn Bộ Repository (Full Repository Canonical Tests):
- **1359 passed**
- **0 failed**
- **152 skipped** (chỉ gồm các sidecar tùy chọn khi không chạy docker)
- **0 xfailed**
- **Canonical Run Duration**: `63.76s`

### Phạm Vi Quyền Riêng Tư (Privacy Scope):
- **DOCX_SAFE_ZERO_EGRESS**: **`PASS`**  
  *DOCX Safe/Lossless cleaning pipeline performs entirely locally and does not make network requests.*
- **APPLICATION_HAS_OPTIONAL_NETWORK_FEATURES**: **`TRUE`**  
  *Optional supported plain-text rewrite backends may access the network only when explicitly enabled by the user.*

---

## 5. Bằng Chứng Bác Bỏ Tệp Lỗi Cũ (KNOWN HISTORICAL FAILURES)

Bộ kiểm chứng Fail-Closed đã được thẩm định độc lập trên 2 negative witnesses và từ chối xuất xưởng thành công:

1. **`02_BAD_OUTPUT_RUN_EXPLOSION.docx`**:
   - **Lỗi**: Run explosion từ 288 vọt lên 6,467 runs ($+2,145\%$), mất ngắt trang (5 -> 4).
   - **Kết quả Validator**: **REJECTED CORRECTLY** (Bị chặn đứng ngay tại Layer 4 Structural Invariants).
2. **`03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION.docx`**:
   - **Lỗi**: Run explosion (6,467 runs), mất ngắt trang (5 -> 4), vỡ layout và mất 1 trang tài liệu (19 -> 18 trang).
   - **Kết quả Validator**: **REJECTED CORRECTLY** (Bị chặn đứng và rollback hoàn toàn).

---

## 6. Trình Tự Thẩm Định Đề Xuất (REVIEW ORDER)

Dành cho auditor và reviewer độc lập để kiểm tra gói bàn giao:

1. Đọc tệp tổng quan: [`00_REVIEW_SUMMARY.md`](00_REVIEW_SUMMARY.md)
2. Kiểm tra báo cáo đo kiểm 5 tầng: [`evidence/real_document_fidelity_report_v2.json`](evidence/real_document_fidelity_report_v2.json)
3. Kiểm tra tính bất biến của các thành viên OOXML: [`evidence/non_target_part_hashes.json`](evidence/non_target_part_hashes.json)
4. Kiểm tra so sánh thị giác từng pixel: [`evidence/visual_regression_report.json`](evidence/visual_regression_report.json)
5. Kiểm tra log thực thi toàn bộ test suite: [`evidence/full_pytest_output.txt`](evidence/full_pytest_output.txt)
6. So sánh cặp tài liệu đối chiếu: [`documents/01_GOLDEN_ORIGINAL_UNTOUCHED.docx`](documents/01_GOLDEN_ORIGINAL_UNTOUCHED.docx) vs [`documents/04_CANDIDATE_LOSSLESS_OUTPUT.docx`](documents/04_CANDIDATE_LOSSLESS_OUTPUT.docx)
7. Đọc tài liệu phát hành chính thức: [`01_RELEASE_NOTES.md`](01_RELEASE_NOTES.md), [`02_MASTER_IMPLEMENTATION_PLAN.md`](02_MASTER_IMPLEMENTATION_PLAN.md), [`03_README.md`](03_README.md).
