# Bot Hiếu Biểu

Telegram bot serverless cho quản lý SKU, nhận diện SKU bằng ảnh, số lượng đơn, reminder và hỏi đáp.

Database production đã chọn: **Supabase Postgres**.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Cập nhật `.env`, sau đó chạy migration và test:

```powershell
python -m alembic upgrade head
python -m pytest
python -m ruff check .
python -m mypy
```

Với Supabase, dùng connection string dành cho server/transaction pooler nếu môi trường
Vercel không kết nối được trực tiếp bằng IPv6. Giữ query parameter SSL do Supabase cung cấp.

## Luồng phát triển hiện tại

- Webhook đã có secret validation và deduplicate `update_id`. Allowlist người dùng đang tạm tắt;
  đặt `TELEGRAM_ENFORCE_ALLOWLIST=true` để bật lại.
- Intent router dùng Gemini Structured Output với primary model và fallback giới hạn qua
  `GEMINI_FALLBACK_MODELS`.
- `/help`, `/sku`, `/orders` và `/reminders` được parse bằng code, không tiêu quota Gemini.
- QA được trả lời trong cùng request phân loại intent, không gọi AI lần thứ hai.
- Các câu trả lời làm rõ được nhớ theo từng user/chat trong 30 phút, nên nội dung và thời gian có
  thể được cung cấp qua nhiều tin nhắn liên tiếp.
- Reminder tách giờ sự kiện và giờ gửi nhắc. Câu `18h ngày 17/9 đi nhậu` mặc định nhắc lúc 16h
  (trước 2 giờ); câu `2 tiếng nữa nhắc tôi...` gửi nhắc đúng sau 2 giờ và không bị trừ thêm.
- Tin xác nhận, kết quả, danh sách và thông báo reminder dùng định dạng thẻ dễ quét: tiêu đề,
  nội dung, thứ/ngày, giờ sự kiện và giờ nhắc; timestamp ISO chỉ dùng nội bộ.
- Lịch sử trao đổi hoàn tất được giữ 30 ngày. Bot chỉ gửi tối đa 8 lượt gần nhất đã giới hạn độ dài
  cho Gemini, đủ hiểu “cái vừa rồi” nhưng không làm token tăng theo toàn bộ lịch sử.
- Bot gửi trạng thái Telegram `typing` khi xử lý; lỗi/quota Gemini trả thông báo thay vì im lặng.
- SKU, order, pending confirmation và reminder worker đã có service layer.
- SKU và order hỗ trợ sửa/xóa bằng câu lệnh tự nhiên có bước xác nhận. `/orders` hiển thị UUID
  để chọn đúng order; SKU còn order sẽ không bị xóa trực tiếp.
- Có thể gửi ảnh kèm chú thích `đây là mã SKU VAY01` (hoặc gửi câu này trước rồi gửi ảnh),
  xác nhận để lưu. Những lần sau chỉ cần gửi ảnh; bot tra bằng mã ảnh Telegram và dấu vân tay
  nội dung, không gọi Gemini. Ánh xạ ảnh được giữ lâu dài trong database, không hết hạn sau 30 phút.
- `/api/check-reminders` yêu cầu `Authorization: Bearer <REMINDER_CRON_SECRET>`.
- Webhook production trên Vercel đã được smoke-test với Telegram thật.

## Lệnh nhanh không dùng AI

```text
/help
/sku <mã hoặc tên mẫu>
/orders [YYYY-MM hoặc YYYY-MM-DD]
/reports [YYYY-MM hoặc YYYY-MM-DD]
/reminders
ảnh + caption: đây là mã SKU VAY01
```

## Nhập số đơn theo người từ ảnh

Gửi ảnh chụp danh sách tên/số đơn (tối đa 30 dòng), có thể kèm ngày trong caption. Bot dùng
Gemini để đọc ảnh chưa nhận diện là SKU; ảnh SKU đã biết vẫn được tra như trước. Có thể thêm
caption `báo cáo số đơn` để chọn rõ luồng báo cáo.

- Thiếu ngày trong ảnh và caption: bot đề xuất hôm nay theo UTC+7, hiển thị ngày cụ thể và
  toàn bộ số liệu. Chưa lưu cho đến khi bấm **✅ Đúng**.
- Bấm **❌ Không** để sửa: `/ngay 15/09/2026`, `/sua 2 Huyền: 97`, `/xoadong 2`.
  `/xacnhan` hiện lại bản xem trước; `/huy` bỏ bản nháp. Dòng mờ hoặc tên trùng phải sửa trước.
- Nếu cùng người/ngày đã có dữ liệu, bản xem trước hiển thị số cũ → số mới. Xác nhận thay thế
  các dòng hiển thị, không cộng dồn và không xóa những người không có trong ảnh mới.
- `/reports 2026-09-16` xem ngày; `/reports 2026-09` xem tháng/xếp hạng; `/reports` xem tháng
  hiện tại. Alias `/baocao` có cùng cú pháp. Có thể hỏi tự nhiên “ai nhiều đơn nhất tháng này?”.
- Dữ liệu tách theo Telegram user và chat; tên giữ nguyên dấu, không tự gộp biệt danh. Cần dùng
  tên thống nhất qua các ngày. Báo cáo hiển thị số ngày có dữ liệu và đồng hạng, chưa tính tiền thưởng.

Tính năng này **đã kiểm tra local, chưa deploy/smoke-test production**. Trước khi deploy phiên bản
mới, chạy `python -m alembic upgrade head` trên database đích để thêm bảng `person_reports`
(migration `20260916_0006`). Dùng cấu hình Gemini hiện có với model hỗ trợ đọc ảnh. Kiểm tra ảnh
thật thiếu ngày → sửa ngày → xác nhận → `/reports`, ảnh trùng người/ngày và callback bấm lại.

## Đăng ký webhook

Sau khi deploy lên URL production ổn định:

```powershell
python scripts/set_webhook.py https://your-project.vercel.app
```

Không commit `.env` hoặc token/secret thật.

Cron ngoài gọi `GET https://<production-domain>/api/check-reminders` mỗi 1–5 phút và
gửi header `Authorization: Bearer <REMINDER_CRON_SECRET>`.
