# ARCHITECTURAL AUDIT REPORT: WATERMARK REMOVAL PIPELINE

## 1. Executive Summary
Báo cáo kiểm toán kiến trúc toàn diện của repository `guillaumemeyer/watermarks-remover` nhằm làm rõ luồng dữ liệu, xác định các điểm có rủi ro làm mất độ trung thực tài liệu (document fidelity), và thiết lập hàng rào kỹ thuật bảo vệ các định dạng tệp tin.

---

## 2. Trả lời 9 Câu hỏi Kiến trúc Upstream

### 1. Luồng xử lý OOXML (DOCX, XLSX, PPTX) của Upstream hoạt động như thế nào?
- **Upstream**: Sử dụng `zipfile.ZipFile` đọc toàn bộ thành viên lưu vào RAM. Duyệt qua từng entry:
  - Nếu là `docProps/core.xml` hoặc `docProps/app.xml`: dùng regex tag streaming xóa các trường provenance (`dc:creator`, `cp:lastModifiedBy`, `Application`, v.v.).
  - Nếu là `customXml/`: xóa bỏ entry (`drop part`).
  - Nếu là `_rels/*.rels`: regex quét xóa `<Relationship>` trỏ vào part bị drop.
  - Nếu là text XML: chạy Layer A (`_scrub_docx_text`, `_scrub_xlsx_text`, `_scrub_pptx_text`).
  - Ghi lại ra một buffer `ZipFile` mới với `compression=ZIP_DEFLATED`.

### 2. Sự khác biệt căn bản giữa Layer A và Layer B trong Upstream là gì?
- **Layer A (Deterministic Unicode Scrub)**: Quét và loại bỏ các ký tự Unicode vô hình (Zero-width space, invisible joiners, directional overrides, tag characters). Đây là thao tác vi mô, không làm thay đổi các từ nhìn thấy.
- **Layer B (Statistical Token Watermark Rewrite)**: Đối phó với watermark thống kê (như SynthID text) bằng cách **viết lại toàn bộ văn bản bằng LLM** (paraphrase, MLM masking).
- **Nguyên tắc Invariant**: **Layer B CHỈ ÁP DỤNG CHO TEXT THUẦN TÚY (Plain text)**. Cấm tuyệt đối áp dụng Layer B lên các định dạng tài liệu có cấu trúc (DOCX/ODT/PDF) vì LLM paraphrase sẽ phá hủy 100% ngữ nghĩa nguyên bản và làm hỏng liên kết run formatting.

### 3. Vấn đề của hàm `_split_text` và việc gộp paragraph trong `docx_statistical.py` cũ?
- Module `docx_statistical.py` cũ (đã xóa) cố gắng paraphrase từng đoạn văn:
  - Gom toàn bộ các run `<w:r>` trong một đoạn `<w:p>` thành 1 chuỗi dài.
  - Chuỗi sau khi được LLM paraphrase bị băm nhỏ ngược lại theo tỷ lệ độ dài cũ (`weights`).
  - Hệ quả: Khoảng trắng ngăn cách giữa 2 từ rơi vào ranh giới run bị xóa bỏ, thẻ `<w:t>` bị mất `xml:space="preserve"`, gây ra hiện tượng **dính chữ hàng loạt** (`"Quản lý"` $\rightarrow$ `"Quảnlý"`).

### 4. Tại sao `normalize_spaces=True` là hành vi nguy hiểm đối với Word?
- Trong tiếng Việt và typography quốc tế:
  - `U+00A0` (Non-breaking space / NBSP) dùng để giữ số và đơn vị (vd: "100 km", "Điều 1"), hoặc giữ tên riêng cùng một dòng.
  - `U+202F` (Narrow no-break space) dùng cho dấu chấm phẩy, dấu hai chấm trong typography tiếng Pháp.
  - `normalize_spaces=True` chuyển đổi toàn bộ các ký tự này thành `U+0020` (Space thường), phá vỡ toàn bộ quy tắc ngắt dòng (line wrap), căn lề justify, và cấu trúc trang văn bản.
- **Quy tắc bất biến**: DOCX cleaner bắt buộc mặc định `normalize_spaces = False`.

### 5. Tại sao cần thuộc tính `xml:space="preserve"` trên thẻ `<w:t>`?
- Theo tiêu chuẩn XML 1.0 và WordprocessingML (ECMA-376 / ISO 29500):
  - Mọi thẻ `<w:t>` không có thuộc tính `xml:space="preserve"` sẽ bị trình phân tích cú pháp XML tự động loại bỏ (trim) các khoảng trắng ở đầu và cuối (leading/trailing whitespace), đồng thời thu gọn các khoảng trắng liền kề thành 1 khoảng trắng.
  - Do đó, nếu một run sau khi xóa watermark carrier bắt đầu hoặc kết thúc bằng khoảng trắng, **bắt buộc phải có `xml:space="preserve"`**.

### 6. Xử lý các run rỗng (Empty runs) sau khi xóa carrier?
- Nếu một run ban đầu chỉ chứa carrier (ví dụ toàn ZWSP) và sau khi xóa thì trở thành rỗng:
  - **KHÔNG ĐƯỢC XÓA RUN NODE** khỏi cây XML (không xóa `<w:r>`).
  - Giữ lại `<w:r><w:t></w:t></w:r>` hoặc `<w:r><w:t/> </w:r>`.
  - **Lý do**: Xóa run node sẽ làm gãy các tham chiếu chỉ mục `rId`, bookmark ranges (`<w:bookmarkStart>`, `<w:bookmarkEnd>`), comment ranges, và track changes revisions.

### 7. Tại sao phương pháp Patching tối thiểu (Minimal In-Place Patching) vượt trội so với DOM Rebuilding?
- Khi dùng thư viện nạp toàn bộ DOM (như `xml.dom.minidom` hay dump lại toàn bộ `ElementTree`):
  - Thứ tự thuộc tính XML bị thay đổi.
  - Namespace prefixes bị định nghĩa lại (vd: `xmlns:w`, `xmlns:r`).
  - Thẻ tự đóng `<w:t/>` bị đổi thành `<w:t></w:t>` hoặc ngược lại.
  - Microsoft Word sẽ phát hiện file bị thay đổi toàn diện và có thể kích hoạt cơ chế kiểm tra bảo mật.
- **In-Place Minimal Patching**: Chỉ thay thế chính xác các byte của thẻ `<w:t>` có chứa carrier, giữ nguyên 100% byte của tất cả các thẻ xung quanh.

### 8. Cơ chế bảo vệ OPC ZIP Package?
- Gói OPC là một file ZIP đặc biệt. Nhiều phần mềm sinh file (vd: WPS Office, Google Docs, LibreOffice, Microsoft Word) có cách sắp xếp thành viên trong ZIP, compression method, và extra header fields khác nhau.
- Cleaner phải đọc bảng `infolist()` ban đầu, giữ nguyên thứ tự `member_order`, giữ nguyên `ZipInfo.flag_bits`, `compress_type`, chỉ thay đổi payload của những part nằm trong kế hoạch `MutationPlan`.

### 9. Cơ chế Fail-Closed hoạt động ra sao?
- Mọi file sau khi xử lý qua candidate patcher đều phải đi qua `DocxFidelityValidator`.
- Nếu phát hiện bất kỳ sai khác nào:
  1. Hủy bỏ file kết quả ứng viên.
  2. Ghi nhật ký lỗi kèm diff chi tiết.
  3. Trả về đúng bản gốc byte-for-byte cho người dùng.
  4. Đảm bảo an toàn 100%: **Thà không xóa được watermark còn hơn làm hỏng file của người dùng**.

---

## 3. Bản đồ các điểm gọi `normalize_spaces` trong Codebase

| Tệp / Module | Hàm | Giá trị mặc định | Hành vi được quy định |
| :--- | :--- | :--- | :--- |
| `service/scripts/text_unicode.py` | `clean_text` | `True` | Dành cho Plain Text; không được dùng trực tiếp trên DOCX XML |
| `service/scripts/container_meta.py` | `clean_docx` | **`False`** | **Bắt buộc False** để bảo toàn NBSP và ngắt dòng |
| `service/scripts/container_meta.py` | `clean_xlsx` | `True` | Cho phép True trên chuỗi cell text nếu người dùng yêu cầu |
| `service/scripts/container_meta.py` | `clean_pptx` | `True` | Cho phép True trên slide text nếu người dùng yêu cầu |
| `service/scripts/container_meta.py` | `clean_odt` | `False` | Khuyến nghị False cho văn bản ODF |
| `service/scripts/container_meta.py` | `clean_container` | `True` | Route sang `clean_docx` phải truyền `normalize_spaces=False` |
| `service/scripts/server.py` | `/clean` endpoint | Options payload | Tự động hạ cờ `normalize_spaces=False` khi định dạng là DOCX |

---

## 4. Sơ đồ Dòng Dữ liệu từ Request đến Output

```
[User Upload: Web UI / CLI / HTTP POST]
             │
             ▼
[format_dispatch.py: Phân loại định dạng dựa trên Magic Bytes / Phần mở rộng]
             │
   ┌─────────┴──────────────────────────────┐
   ▼                                        ▼
[Plain Text]                          [Container: DOCX]
   │                                        │
   ▼                                        ▼
[text_unicode.py: Layer A]           [docx.package.DocxPackage: Audit OPC]
   │                                        │
   ▼                                        ▼
[rewrite_text.py: Optional Layer B]   [docx.detector.DocxDetector: Build Plan]
   │                                        │
   ▼                                        ▼
[Output Text]                        [docx.patcher.DocxPatcher: Minimal Patch]
                                            │
                                            ▼
                                     [docx.validator.DocxFidelityValidator]
                                            │
                                 ┌──────────┴──────────┐
                             [PASS]                 [FAIL]
                                 │                     │
                                 ▼                     ▼
                         [Cleaned DOCX]        [Fail-Closed: Rollback Original]
```
