# Trung tâm Tài liệu & Báo cáo (Documentation Hub)

Chào mừng bạn đến với trung tâm tài liệu kỹ thuật và báo cáo nghiệm thu của dự án **`watermarks-remover` / ClearMark Engine (v2.0.0)**.

Toàn bộ tài liệu, kế hoạch và báo cáo kiểm toán đã được phân loại và gom gọn theo các khu vực chuyên biệt bên dưới:

---

## 📂 Cấu trúc Tài liệu & Báo cáo

```
docs/
├── README.md                          # Mục lục điều hướng trung tâm (Tài liệu này)
├── reports/                           # Toàn bộ báo cáo kiểm toán & nghiệm thu
│   ├── README.md                      # Mục lục chuyên biệt cho báo cáo
│   ├── MASTER_REVALIDATION_REPORT.md  # Báo cáo nghiệm thu Lossless DOCX tổng thể v2.0.0
│   ├── architecture_audit.md          # Báo cáo kiểm toán kiến trúc & gốc rễ lỗi dính chữ
│   ├── security_audit.md              # Báo cáo kiểm toán an ninh, an toàn bộ nhớ & Zero Egress
│   └── synthid-text-benchmark.md      # Đánh giá benchmark SynthID-Text
├── windows-autostart.md               # Hướng dẫn cấu hình khởi động ngầm cùng Windows
└── plans/                             # Kế hoạch phát triển & ý tưởng mở rộng
    └── ideas/
        └── deployment-docker-cli-api.md
```

---

## 📑 1. Báo cáo Nghiệm thu & Kiểm toán Kỹ thuật ([`docs/reports/`](reports/))

- [**Báo cáo Nghiệm thu Tổng thể (MASTER_REVALIDATION_REPORT.md)**](reports/MASTER_REVALIDATION_REPORT.md):  
  *Báo cáo quan trọng nhất*. Trình bày toàn bộ kết quả nghiệm thu trên bộ 3 tệp regression thực tế, khóa Golden Baseline theo SHA-256, kiểm thử chặn lỗi trên negative witnesses, đo kiểm 19/19 trang visual pixel similarity 1.0, đối chiếu byte-level từng OOXML member, và tóm tắt kết quả full 1,348 tests repository.
- [**Kiểm toán Kiến trúc (architecture_audit.md)**](reports/architecture_audit.md):  
  Phân tích chi tiết mô hình `DETECT -> PLAN -> MINIMAL PATCH -> VALIDATE -> OUTPUT` thay thế cho anti-pattern cũ `PARSE -> NORMALIZE -> REBUILD`.
- [**Kiểm toán An ninh & Quyền riêng tư (security_audit.md)**](reports/security_audit.md):  
  Xác thực mô hình 0 network egress cho DOCX, bảo vệ chống ZipSlip, ZipBomb, XXE injection và memory safety.
- [**Benchmark SynthID-Text (synthid-text-benchmark.md)**](reports/synthid-text-benchmark.md):  
  Đo kiểm hiệu năng và độ nhạy của bộ phát hiện watermark thống kê SynthID-Text.

---

## 🛠️ 2. Kế hoạch Triển khai & Ghi chú Phát hành (Root Level)

- [**MASTER_IMPLEMENTATION_PLAN.md**](../MASTER_IMPLEMENTATION_PLAN.md):  
  Kế hoạch 17 Phases toàn diện từ Freeze Baseline (Phase 0) đến Release Candidate (Phase 16), toàn bộ 17 Phase đã đạt **PASS**.
- [**RELEASE_NOTES.md**](../RELEASE_NOTES.md):  
  Thông cáo phát hành chính thức phiên bản v2.0.0, so sánh kiến trúc trước/sau refactor, hướng dẫn khởi chạy nhanh cho người dùng cuối qua Web UI (cổng `8765`), PowerShell và CLI.

---

## 💻 3. Hướng dẫn Vận hành & Cài đặt

- [**Hướng dẫn Tự khởi động trên Windows (windows-autostart.md)**](windows-autostart.md):  
  Cách thức đăng ký dịch vụ ClearMark chạy ngầm tự động mỗi khi đăng nhập Windows mà không cần cài đặt Docker.
- [**Hướng dẫn Sử dụng Chính (README.md)**](../README.md):  
  Tài liệu giới thiệu tổng thể, cài đặt agent skill, API HTTP, Docker Compose stack và các CLI tools.

---

## 🗄️ 4. Dữ liệu Kiểm toán Máy đọc (Machine-Readable Artifacts)

Toàn bộ các tệp định dạng JSON ghi nhận bằng chứng kiểm toán được gom gọn tại thư mục [`artifacts/`](../artifacts/):
- [`artifacts/golden_documents.json`](../artifacts/golden_documents.json): Registry bất biến khóa file chuẩn bằng mã băm SHA-256.
- [`artifacts/real_document_fidelity_report_v2.json`](../artifacts/real_document_fidelity_report_v2.json): Báo cáo đo kiểm 5 tầng cho Candidate output.
- [`artifacts/visual_regression_report.json`](../artifacts/visual_regression_report.json): So khớp pixel 19/19 trang render qua LibreOffice.
- [`artifacts/non_target_part_hashes.json`](../artifacts/non_target_part_hashes.json): Bảng đối chiếu mã băm từng OOXML member.
- [`artifacts/README.md`](../artifacts/README.md): Mục lục giải thích chi tiết các tệp JSON artifacts.
