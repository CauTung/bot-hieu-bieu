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
/reminders
ảnh + caption: đây là mã SKU VAY01
```

## Đăng ký webhook

Sau khi deploy lên URL production ổn định:

```powershell
python scripts/set_webhook.py https://your-project.vercel.app
```

Không commit `.env` hoặc token/secret thật.

Cron ngoài gọi `GET https://<production-domain>/api/check-reminders` mỗi 1–5 phút và
gửi header `Authorization: Bearer <REMINDER_CRON_SECRET>`.
