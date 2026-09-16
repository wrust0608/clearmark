# KẾ HOẠCH DỌN DẸP AN TOÀN KHO LƯU TRỮ (CLEANUP PLAN v2.0.0)

Kế hoạch này thực hiện phân loại toàn diện mọi tệp tin trong repository theo chính sách Safe Repository Cleanup (Section 13.6).

---

## 1. Phân loại Tệp tin (Categorization)

### A. KEEP (Giữ nguyên làm tài liệu chuẩn & mã nguồn phục vụ vận hành)
- **Tài liệu cốt lõi**:
  - `README.md` (Tài liệu giới thiệu chính)
  - `RELEASE_NOTES.md` (Ghi chú phát hành chuẩn v2.0.0)
  - `MASTER_IMPLEMENTATION_PLAN.md` (Kế hoạch thực thi 17 phases)
  - `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`
- **Bộ mẫu chuẩn & Negative Regression Witnesses**:
  - `01_GOLDEN_ORIGINAL_UNTOUCHED.docx` (True Golden Original)
  - `02_BAD_OUTPUT_RUN_EXPLOSION.docx` (Witness lỗi Run Explosion)
  - `03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION.docx` (Witness lỗi Mất trang / Layout)
  - `04_CANDIDATE_LOSSLESS_OUTPUT.docx` (Valid Candidate Output)
  - `WATERMARK_DOCX_3_BASELINES.zip` (Gói đối chiếu 3 baselines ban đầu)
- **Báo cáo chuyên sâu (`docs/reports/*`)**:
  - `docs/reports/MASTER_REVALIDATION_REPORT.md`
  - `docs/reports/security_audit.md`
  - `docs/reports/architecture_audit.md`
  - `docs/reports/synthid-text-benchmark.md`
  - `docs/reports/README.md`
- **Gói bằng chứng nghiệm thu (`artifacts/final_acceptance/*`)**:
  - `golden_documents.json`, `real_document_fidelity_report_v2.json`, `visual_regression_report.json`, `non_target_part_hashes.json`, `performance_report.json`, `release_verification.json`, `full_pytest_output.txt`
  - `verification_docs/` (`01_GOLDEN_ORIGINAL_UNTOUCHED.docx`, `04_CANDIDATE_LOSSLESS_OUTPUT.docx`)
- **Mã nguồn & Launchers**:
  - `service/scripts/docx/*` (Toàn bộ 7 modules của Lossless DOCX Subsystem)
  - `service/scripts/*` (`container_meta.py`, `server.py`, `format_dispatch.py`, `text_unicode.py`, v.v.)
  - `service/web/*` (Giao diện web ClearMark)
  - `clearmark-manager.ps1`, `ClearMark.cmd`, `Open-ClearMark.cmd`, `Stop-ClearMark.cmd`, `start-app.ps1`
- **Test suite toàn diện**:
  - `tests/*` (Toàn bộ 1,356 test cases bao gồm `test_documentation_consistency.py`)

### B. ARCHIVE (Lưu trữ cách ly phục vụ hồi quy lịch sử)
- `docs/history/INVALID_BASELINE_REPORT.md` (Báo cáo đo kiểm trên tệp lỗi cũ, có gắn cảnh báo)
- `docs/history/real_document_fidelity_report_v1_flawed.json` (Báo cáo máy đọc v1 cũ)
- `artifacts/baseline_metrics.json` (Snapshot Phase 0 có gắn nhãn lịch sử)

### C. DELETE (Các tệp rác / sinh tạm trong quá trình chạy thử nghiệm)
- `.run/07-statistical-clean.docx` (Tệp candidate tạm thời sinh ra bởi thuật toán paraphrase cũ)
- `.run/07-statistical-report.json` (Báo cáo tạm thời từ quá trình chạy rewrite cũ)
- `.run/llama-b10985-win-cpu-x64.zip` (Tệp ZIP công cụ tải về trong quá trình test LLM cũ)
- `.run/launcher.log` (Log launcher cũ đã hết hạn)
- `.run/server.log` (Log rỗng)
- `.run/server-error.log` (Log rỗng)
- `.run/clearmark.pid.json` (Bản ghi PID của phiên làm việc cũ)

---

## 2. Nguyên tắc An toàn (Archive Before Delete)

Mọi tệp thuộc nhóm **DELETE** bắt buộc phải được đóng gói vào:
`artifacts/archive/PRE_FINAL_CLEANUP_BACKUP.zip`
kèm mã băm `artifacts/archive/PRE_FINAL_CLEANUP_BACKUP_SHA256.txt` trước khi thực hiện xóa.

---

## 3. Nhật ký Xác nhận Không Có Tệp Tên Trùng Lặp
Không tồn tại bất kỳ tệp nào mang định dạng trùng lặp như `(1)`, `(2)`, `copy` trong kho lưu trữ.
