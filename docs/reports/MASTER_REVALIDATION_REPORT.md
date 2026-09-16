# BÁO CÁO NGHIỆM THU TỔNG THỂ: GOLDEN BASELINE LOCK & LOSSLESS DOCX ACCEPTANCE

> **Dự án**: `watermarks-remover` / ClearMark Engine  
> **Phiên bản**: v2.0.0 (Lossless Document Fidelity Subsystem)  
> **Thời điểm nghiệm thu**: Tháng 9/2026  
> **Trạng thái**: **APPROVED FOR PRODUCTION RELEASE (PASS 100%)**  

---

## 1. Mục tiêu & Nguyên tắc Nghiệm thu

Bản báo cáo này tổng hợp kết quả thẩm định và nghiệm thu độc lập trên bộ 3 tệp regression thực tế (`WATERMARK_DOCX_3_BASELINES.zip`), tuân thủ chặt chẽ nguyên lý:
- **Kiến trúc cốt lõi**: `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT`
- **Loại bỏ vĩnh viễn**: Anti-pattern `PARSE -> NORMALIZE -> REBUILD`
- **Bất biến số 1 (Invariant #1)**: Document Fidelity là ưu tiên tuyệt đối. Nếu việc xóa watermark có nguy cơ làm thay đổi cấu trúc hoặc layout, hệ thống ưu tiên bảo toàn nguyên vẹn tài liệu gốc (Fail-Closed).
- **Định danh Baseline**: Khóa bằng mã băm mật mã học (SHA-256), tuyệt đối không nhận diện theo tên tệp.

---

## 2. Khóa Golden Original Mật mã học (Cryptographic Baseline Lock)

Tệp gốc duy nhất trước khi làm sạch đã được xác minh và lưu trữ vào registry bất biến [`artifacts/golden_documents.json`](../../artifacts/golden_documents.json):

| Chỉ số kỹ thuật | Yêu cầu Baseline | Kết quả Đo kiểm Thực tế | Đánh giá |
| :--- | :--- | :--- | :---: |
| **Đường dẫn** | `01_GOLDEN_ORIGINAL_UNTOUCHED.docx` | `01_GOLDEN_ORIGINAL_UNTOUCHED.docx` | **PASS** |
| **Kích thước** | `49,959` bytes | `49,959` bytes | **PASS** |
| **SHA-256** | `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` | `c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d` | **PASS** |
| **Paragraphs (`w:p`)** | 204 | 204 | **PASS** |
| **Runs (`w:r`)** | 288 | 288 | **PASS** |
| **Tables (`w:tbl`)** | 1 | 1 | **PASS** |
| **Table Rows (`w:tr`)** | 7 | 7 | **PASS** |
| **Table Cells (`w:tc`)** | 49 | 49 | **PASS** |
| **Manual Page Breaks (`w:br[type=page]`)** | 5 | 5 | **PASS** |
| **Sections (`w:sectPr`)** | 1 | 1 | **PASS** |
| **ZIP Package Members** | 15 | 15 | **PASS** |
| **LibreOffice Rendered Pages** | 19 | 19 | **PASS** |

---

## 3. Kiểm định Validator bằng Negative Witnesses

Validator mới được kiểm thử độc lập trên 2 chứng nhân lỗi (Negative Witnesses) nhằm chứng minh khả năng chặn đứng mọi suy thoái tài liệu:

### 3.1. Candidate A (`02_BAD_OUTPUT_RUN_EXPLOSION.docx`)
- **Kích thước**: 66,394 bytes | **SHA-256**: `18627cfd57e661abc24ba3d8febb6802420b871327d05b219f11219dc16fc018`
- **Kết quả Validator**: **`FAIL` (CHÍNH XÁC)**
- **Lỗi phát hiện**:
  - Run Explosion: Số lượng run tăng vọt từ `288` lên `6,467` runs ($+2,145\%$).
  - Mất ngắt trang: Manual page breaks bị sụt giảm từ `5` xuống còn `4`.
  - Non-target parts hash delta: Các part không mục tiêu bị thay đổi do re-serialization phá hủy.
  - Visible text regression: Xuất hiện hiện tượng dính chữ (*Word gluing*).

### 3.2. Candidate B (`03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION.docx`)
- **Kích thước**: 63,538 bytes | **SHA-256**: `a9dcf7fc3b0f0d43e1510f6775f286d0fe5b100b78b68a6126792159738d8146`
- **Kết quả Validator**: **`FAIL` (CHÍNH XÁC)**
- **Lỗi phát hiện**:
  - Vẫn tồn tại Run Explosion: `6,467` runs thay vì `288` runs gốc.
  - Mất ngắt trang: Manual page breaks bị sụt giảm từ `5` xuống `4`.
  - Layout regression: LibreOffice render chỉ ra **18 trang** (mất 1 trang so với 19 trang gốc).

---

## 4. Nghiệm thu Candidate Mới (`04_CANDIDATE_LOSSLESS_OUTPUT.docx`)

Tệp làm sạch mới được sinh trực tiếp từ Golden Original thông qua `clean_docx_lossless` kết hợp Raw OPC ZIP Copier:

- **Tệp xuất ra**: [`04_CANDIDATE_LOSSLESS_OUTPUT.docx`](../../04_CANDIDATE_LOSSLESS_OUTPUT.docx)
- **Kích thước**: `49,395` bytes
- **SHA-256**: `7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297`
- **Thời gian xử lý**: `~231 ms`

```json
{
  "golden_sha256": "c05ca5c1be3b020b75d5763cf22061879a255b3c4f57b0455ae562b54809f58d",
  "golden_size": 49959,
  "candidate_sha256": "7aa5549f6a0e0b78fa39245c0e79503b2cc9defd6cffbfa5c8a833072d430297",
  "candidate_size": 49395,
  "paragraphs": [204, 204],
  "runs": [288, 288],
  "tables": [1, 1],
  "table_rows": [7, 7],
  "table_cells": [49, 49],
  "manual_page_breaks": [5, 5],
  "sections": [1, 1],
  "pages": [19, 19],
  "visible_text_exact": true,
  "non_target_parts_identical": true,
  "relationship_ids_preserved": true,
  "formatting_fingerprint_equal": true,
  "visual_validation": "pass",
  "overall": "PASS"
}
```

> [!NOTE]
> **Lưu ý Tài liệu Thực tế (Real Document Note)**: Trên mẫu chuẩn `01_GOLDEN_ORIGINAL_UNTOUCHED.docx`, `word/document.xml` là byte-identical trước và sau khi làm sạch. Hai part thay đổi duy nhất là metadata provenance (`docProps/core.xml` xóa `cp:lastModifiedBy` và `docProps/app.xml` xóa `Application`). Do đó, mẫu này minh chứng cho tính toàn vẹn tài liệu và khả năng tẩy sạch metadata. Khả năng gỡ bỏ ký tự Unicode carrier trong phần thân được kiểm chứng độc lập thông qua bộ synthetic/regression fixtures chuyên dụng.

---

## 5. Báo cáo Byte Hash Các Thành phần Không Mục tiêu (Non-Target OOXML Parts)

| Tên OOXML Part | Golden Uncompressed SHA-256 | Candidate Uncompressed SHA-256 | Golden Raw Compressed SHA-256 | Candidate Raw Compressed SHA-256 | Kết quả |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `[Content_Types].xml` | `73bd090a91ace77d...` | `73bd090a91ace77d...` | `b070ef52e59308be...` | `b070ef52e59308be...` | **SAME** |
| `_rels/.rels` | `e19238d7a71fa7a2...` | `e19238d7a71fa7a2...` | `aac6aca663d9b582...` | `aac6aca663d9b582...` | **SAME** |
| `word/document.xml` | `2a6b4671f90d8367...` | `2a6b4671f90d8367...` | `95682b3697dc4a00...` | `95682b3697dc4a00...` | **SAME** |
| `word/_rels/document.xml.rels`| `f38260cb34da0c9f...` | `f38260cb34da0c9f...` | `651e72dfafb0fb89...` | `651e72dfafb0fb89...` | **SAME** |
| `word/footnotes.xml` | `39008620c1db740b...` | `39008620c1db740b...` | `dfb0e392a305a852...` | `dfb0e392a305a852...` | **SAME** |
| `word/endnotes.xml` | `3ac117a1ff109642...` | `3ac117a1ff109642...` | `a90c0efec567f8fb...` | `a90c0efec567f8fb...` | **SAME** |
| `word/footer1.xml` | `88657a884c6cafa6...` | `88657a884c6cafa6...` | `a5f42bba46c59c55...` | `a5f42bba46c59c55...` | **SAME** |
| `word/theme/theme1.xml` | `b2295d3198893d2c...` | `b2295d3198893d2c...` | `6471804b4dfaeef4...` | `6471804b4dfaeef4...` | **SAME** |
| `word/settings.xml` | `eb20e2d691d4813b...` | `eb20e2d691d4813b...` | `d76b1f2eaee6fbe0...` | `d76b1f2eaee6fbe0...` | **SAME** |
| `word/numbering.xml` | `85f96f958ed0e48e...` | `85f96f958ed0e48e...` | `ff3fe656f4d36eb8...` | `ff3fe656f4d36eb8...` | **SAME** |
| `word/styles.xml` | `05840e54e56f6b30...` | `05840e54e56f6b30...` | `fa718bc8e63da292...` | `fa718bc8e63da292...` | **SAME** |
| `word/webSettings.xml` | `ee07406206c299bd...` | `ee07406206c299bd...` | `90887189a0cbceb4...` | `90887189a0cbceb4...` | **SAME** |
| `word/fontTable.xml` | `e60abd3bbaed0b07...` | `e60abd3bbaed0b07...` | `5c64c7e63ef27c32...` | `5c64c7e63ef27c32...` | **SAME** |
| `docProps/core.xml` | `2e0307ea03525ad3...` | `a8efbdbf535ed023...` | `...` | `...` | **CHANGED (PLANNED)** |
| `docProps/app.xml` | `6b03dd525d113bd7...` | `87437905421ddd8d...` | `...` | `...` | **CHANGED (PLANNED)** |

> **100% các tệp không mục tiêu đạt nguyên vẹn từng byte cả về uncompressed payload lẫn raw compressed bytes**. Không xảy ra re-serialization DOM hay recompression trên các phần ngoài MutationPlan.

---

## 6. Kiểm định Thị giác & Bố cục (Visual Pixel Regression)

- **Công cụ thực thi**: LibreOffice 25.8 Headless $\rightarrow$ PDF $\rightarrow$ `pypdfium2` (150 DPI) $\rightarrow$ PIL `ImageChops` Pixel Comparison.
- **Trang Golden**: 19 trang.
- **Trang Candidate**: 19 trang.
- **Tương đồng trung bình**: **`1.000000` (100% pixel match)**.
- **Tương đồng tối thiểu**: **`1.000000` (100% pixel match)**.
- **Kết quả**: Cả 19/19 trang đều đạt trạng thái **`IDENTICAL`** tuyệt đối.

---

## 7. Tổng kết Test Suite Toàn bộ Repository

Thực thi test suite hoàn chỉnh bằng `uv run --with pytest pytest`:
- **passed**: **1,359**
- **failed**: **0**
- **skipped**: **152** *(các module sidecar/model ngoài)*
- **xfailed**: **0**
- **duration**: **63.76s**

---

## 8. Giới hạn Kỹ thuật & Ranh giới Fail-Closed

The strict raw OPC copier currently supports the ZIP forms used by standard Word DOCX fixtures in the validated test matrix, including STORED and DEFLATED entries. Unsupported or unvalidated ZIP features must fail closed, including where applicable:
- ZIP64 edge cases
- multi-disk archives
- unsupported compression algorithms
- encrypted ZIP members

Do not silently normalize unsupported archive structures.

*Strict Raw OPC Invariants (13/13 Non-Target Parts)*:  
Uncompressed payload SAME, compressed payload SAME, CRC SAME, compress_type SAME, flag_bits SAME, external_attr SAME, internal_attr SAME, date_time SAME, extra SAME, comment SAME.

---

## 9. Kết luận Nghiệm thu

Hệ thống ClearMark Lossless DOCX Subsystem đã vượt qua toàn bộ các cổng kiểm định chất lượng:
1. Golden Baseline được khóa vĩnh viễn theo mã băm SHA-256.
2. Negative witnesses hỏng đều bị phát hiện và từ chối chính xác bởi validator.
3. Candidate output đạt độ bảo toàn 100% về cấu trúc, định dạng, nội dung và hình ảnh render.
4. Raw ZIP preservation bảo toàn nguyên vẹn byte-for-byte từng compressed member payload và ZIP metadata.
5. Toàn bộ mã nguồn và test suite đạt chuẩn xuất xưởng.

**Trạng thái bàn giao chính thức**: **FINAL RELEASE APPROVED (v2.0.0)**
