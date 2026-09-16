# Thư mục Báo cáo Kỹ thuật (Technical Reports)

Thư mục này tập trung toàn bộ các báo cáo kiểm toán kỹ thuật, báo cáo nghiệm thu và đánh giá chuyên sâu của hệ thống `watermarks-remover` / ClearMark.

---

## 📑 Danh mục Báo cáo

| Báo cáo | Nội dung chính | Trạng thái |
| :--- | :--- | :---: |
| [**MASTER_REVALIDATION_REPORT.md**](MASTER_REVALIDATION_REPORT.md) | **Báo cáo Nghiệm thu Tổng thể v2.0.0**: Khóa Golden Baseline hash, kiểm định Fail-Closed trên negative witnesses, đo kiểm 19/19 trang visual pixel similarity 1.0, non-target OOXML part hashes, và kết quả full 1,348 tests pytest. | **PASS (100%)** |
| [**architecture_audit.md**](architecture_audit.md) | **Kiểm toán Kiến trúc Hệ thống**: Rà soát luồng xử lý upstream, phân tích nguyên nhân gốc rễ lỗi dính chữ và AI paraphrase, thiết lập kiến trúc `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT`. | **VERIFIED** |
| [**security_audit.md**](security_audit.md) | **Kiểm toán An ninh & Quyền riêng tư**: Đánh giá giới hạn an toàn, zero network egress cho DOCX, chống ZipSlip, ZipBomb, XXE injection và an toàn bộ nhớ. | **VERIFIED** |
| [**synthid-text-benchmark.md**](synthid-text-benchmark.md) | **Benchmark SynthID-Text**: Đánh giá tỷ lệ phát hiện và dọn dẹp watermark thống kê SynthID-Text trên mô hình ngôn ngữ lớn. | **VERIFIED** |

---

## 📦 Liên kết Dữ liệu Máy đọc (Machine-Readable Artifacts)

Tất cả các tệp dữ liệu kiểm toán JSON được lưu trữ tập trung tại thư mục [`artifacts/`](../../artifacts/):
- [`artifacts/golden_documents.json`](../../artifacts/golden_documents.json): Registry bất biến định danh tệp mẫu theo mã băm SHA-256.
- [`artifacts/real_document_fidelity_report_v2.json`](../../artifacts/real_document_fidelity_report_v2.json): Báo cáo đo kiểm 5 tầng dữ liệu chi tiết cho DOCX Candidate.
- [`artifacts/visual_regression_report.json`](../../artifacts/visual_regression_report.json): Báo cáo so khớp thị giác từng trang (19/19 trang).
- [`artifacts/non_target_part_hashes.json`](../../artifacts/non_target_part_hashes.json): Bảng so sánh hash của từng member trong gói OPC OOXML.
